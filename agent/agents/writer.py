"""Writer Agent — 체크리스트와 수집된 사실로 검토 보고를 작성한다 (quality LLM, 토큰 스트리밍).

체크리스트는 이미 코드로 확정돼 있다. Writer는 사람이 읽을 보고서를 쓰는 역할이고,
항목을 빠뜨렸는지는 Validator가 코드로 확인한다(Wave 8 재작성 루프).
"""
from ..domain_4m import COMMON
from ..llm.handle import LLMHandle
from ..prompts_4m import WRITER_SYSTEM, request_section
from .research import LINE_STATUS


def _evidence_text(item: dict) -> str:
    ev = item["evidence"]
    if "flow_rule" in ev:
        return f"공정 흐름 {ev['flow_rule']} ({ev['subject']})"
    if "rule" in ev:
        return f"규칙표 ({', '.join(ev['change_types'])})"
    text = f"{ev.get('doc_id')} Rev.{ev.get('rev')} 조항 {ev.get('clause')}" \
        if ev.get("doc_id") else "공통 규정"
    if ev.get("targets"):
        text += f", {'설비' if ev['tool'] == 'equipment' else '라인'} {', '.join(ev['targets'])}"
    return text


def build_user_message(query: str, classification: dict, grading: dict,
                       checklist: list[dict], documents: list[dict], findings: list[dict],
                       feedback: str | None) -> str:
    summary = (f"공장: {classification.get('shop') or COMMON}\n"
               f"변경 유형: {', '.join(classification['change_types'])}\n"
               f"변경 등급: {grading['grade']} ({grading['approver']})\n"
               f"초기유동관리: {grading['initial_flow_period']}")
    items = "\n".join(f"- [{i['id']}] {i['name']} — {_evidence_text(i)}" for i in checklist)
    docs = "\n".join(f"- {d['doc_id']} Rev.{d['rev']} {d['title']}"
                     for d in documents if d["found"])
    facts = "\n".join(f"- {f['target']}: {LINE_STATUS.get(f['status'], f['status'])} "
                      f"{f['note']}".rstrip() for f in findings)
    user = (f"{request_section(query)}\n## 변경 요약\n{summary}\n\n"
            f"## 검증 항목\n{items or '- (없음)'}\n\n"
            f"## 참조 문서\n{docs or '- (없음)'}\n\n## 현장 데이터\n{facts or '- (없음)'}")
    if feedback:
        user += f"\n\n## 검증 반려 사유 (반드시 반영)\n{feedback}"
    return user


async def write(llm: LLMHandle, user: str, on_token=None) -> tuple[str, dict]:
    return await llm.text(WRITER_SYSTEM, user, on_token=on_token)
