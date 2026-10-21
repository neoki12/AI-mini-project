"""LLM-as-a-Judge — 규칙 채점으로는 볼 수 없는 검토 보고서의 품질을 별도 LLM이 채점한다.

규칙 채점(eval/metrics.py)은 체크리스트 항목 ID만 본다. 사람이 읽는 보고서가 근거와 맞는지,
담당자가 바로 쓸 수 있는지는 정답 ID로 잴 수 없어 LLM 평가자에게 맡긴다.

- 근거 충실도(judge_faithfulness): 보고서의 사실 진술(문서·조항·개정판, 수치, 설비 상태)이
  시스템이 실제로 읽은 조항 원문과 현장 데이터로 뒷받침되는가. 지어낸 조항·수치는 감점
- 실무 유용성(judge_usefulness): 항목마다 왜 필요한지와 할 일이 있어 담당자가 바로 실행할 수 있는가

평가 모델은 검토를 만든 모델과 다르게 둔다(자기 선호 편향 방지). 기본은 OpenAI gpt-4o이고
JUDGE_MODEL로 바꾼다. 1~5점 루브릭으로 받고 0~1로 바꿔 다른 지표와 같은 축에 둔다.
루브릭 근거(reason)와 근거 없는 진술 목록은 LangSmith 평가 comment에 남긴다.
"""
import os

from pydantic import BaseModel, Field

JUDGE_SYSTEM = """너는 완성차 공장 4M 변경 검토 보고서를 채점하는 품질 감사관이다.
[출처]는 검토 시스템이 실제로 읽은 표준서 조항 원문, 현장 데이터, 확정된 체크리스트다.
[보고서]만 채점하고, [출처]에 없는 지식으로 보고서를 고쳐 주지 마라.

1) faithfulness (근거 충실도, 1~5)
   보고서의 사실 진술 — 문서 ID·개정판·조항 번호, 수치(기간·횟수·타점 등), 설비·라인 상태,
   항목이 필요한 이유 — 이 [출처]로 뒷받침되는지 본다.
   5: 모든 진술이 출처와 일치  4: 사소한 표현 차이만  3: 근거 없는 진술 1개
   2: 근거 없는 진술 2개 이상이거나 틀린 조항·수치 인용  1: 대부분 출처와 무관하거나 지어냄
2) usefulness (실무 유용성, 1~5)
   품질 담당자가 이 보고서만 보고 무엇을 왜 해야 하는지 알 수 있는지 본다.
   5: 항목마다 이유와 할 일, 등급과 승인자, 현장 이상과 조치가 분명  3: 항목 나열 위주, 이유가 일부 빠짐
   1: 무엇을 해야 하는지 알기 어려움

unsupported에는 출처로 뒷받침되지 않는 진술을 보고서에서 짧게 인용해 적는다 (없으면 빈 목록)."""


class JudgeVerdict(BaseModel):
    faithfulness: int = Field(ge=1, le=5)
    usefulness: int = Field(ge=1, le=5)
    unsupported: list[str] = Field(default_factory=list, max_length=5)
    reason: str = Field(description="채점 근거 2~3문장")


def sources_text(documents: list[dict], findings: list[dict], checklist: list[dict]) -> str:
    """시스템이 실제로 본 출처 — 판사는 이것만으로 보고서 진술을 확인한다."""
    parts = []
    for d in documents:
        if not d.get("found"):
            continue
        parts.append(f"### {d['doc_id']} Rev.{d['rev']} {d['title']}")
        parts += [f"- 조항 {c['no']} {c['title']}: {c['text']}" for c in d.get("clauses", [])]
    if findings:
        parts.append("### 현장 데이터 (MCP Tool 조회)")
        parts += [f"- {f.get('target')}: {f.get('status')} {f.get('note', '')}".rstrip()
                  for f in findings]
    if checklist:
        parts.append("### 확정된 체크리스트")
        parts += [f"- [{i['id']}] {i['name']} — 근거 {i.get('evidence')}" for i in checklist]
    return "\n".join(parts) or "(출처 없음)"


def judge_user(request: str, report: str, sources: str) -> str:
    return f"[요청]\n{request}\n\n[출처]\n{sources}\n\n[보고서]\n{report}"


def to_unit(score: int) -> float:
    """1~5점 → 0~1 (1점=0, 5점=1)."""
    return round((score - 1) / 4, 4)


def build_judge_llm():
    """평가 모델 — 기본 OpenAI gpt-4o. 키가 없으면 None (판사 평가를 건너뛴다)."""
    from agent.llm.handle import LLMHandle
    model = os.getenv("JUDGE_MODEL", "gpt-4o")
    if model.startswith("ollama:"):
        from langchain_ollama import ChatOllama
        name = model.split(":", 1)[1]
        return LLMHandle(model, ChatOllama(model=name, temperature=0, reasoning=False,
                                           num_predict=1024), 0.0, True, timeout=180.0)
    if not os.getenv("OPENAI_API_KEY"):
        return None
    from langchain_openai import ChatOpenAI
    return LLMHandle(f"openai:{model}", ChatOpenAI(model=model, temperature=0, max_tokens=1024,
                                                  request_timeout=120, max_retries=2),
                     0.005, True, timeout=150.0)


async def judge(llm, request: str, report: str, sources: str) -> JudgeVerdict:
    verdict, _ = await llm.structured(JUDGE_SYSTEM, judge_user(request, report, sources),
                                      JudgeVerdict)
    return verdict


def make_evaluator(llm):
    """aevaluate용 비동기 평가자. 보고서가 없거나 판사 호출이 실패하면 점수를 내지 않는다."""
    async def ev_llm_judge(inputs: dict, outputs: dict) -> dict:
        report = outputs.get("report")
        if not report:
            return {"results": []}
        try:
            v = await judge(llm, inputs["message"], report, outputs.get("sources", ""))
        except Exception as exc:   # 판사 실패가 검토 평가 전체를 막지 않게
            return {"results": [{"key": "judge_faithfulness", "score": None,
                                 "comment": f"판사 실패: {type(exc).__name__}"}]}
        note = v.reason + (f" | 근거 없음: {'; '.join(v.unsupported)}" if v.unsupported else "")
        return {"results": [
            {"key": "judge_faithfulness", "score": to_unit(v.faithfulness), "comment": note},
            {"key": "judge_usefulness", "score": to_unit(v.usefulness)}]}
    return ev_llm_judge
