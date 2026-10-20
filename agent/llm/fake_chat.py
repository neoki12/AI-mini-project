"""규칙 기반 결정론 채팅 모델 — LLM_BACKEND=fake와 테스트에서 쓰는 LangChain BaseChatModel.

실제 LLM 호출 없이 파이프라인 전체를 결정론적으로 재현한다. 시스템 프롬프트의
`[agent:이름]` 표식으로 어느 Agent의 호출인지 구분하고, 사용자 메시지의 `## 섹션`을 읽어
domain_4m의 키워드 규칙으로 JSON(구조화 출력) 또는 텍스트를 만든다.

이 파일의 키워드 규칙(_CONDITION_KEYWORDS 등)은 fake 전용이다. 실모델은 조항 본문을 읽고
판단한다 — fake의 정답률이 실모델 성능을 뜻하지 않는다.
"""
import json
import re
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from ..domain_4m import (COMMON, find_equipment_ids, find_lines, guess_change_types,
                         guess_shop)

REVIEW_PATTERN = r"변경|교체|투입|도입|수정|이설|4M|검토|신고"

# 조건부 항목 → 변경 요청에 이 단어 묶음이 모두(하나 이상씩) 있으면 해당 (fake 전용)
_CONDITION_KEYWORDS: dict[str, list[list[str]]] = {
    "EXT-PR-01": [["외판"]],
    "EXT-BD-01": [["전류", "통전", "가압력", "용접 조건"]],
    "EXT-PT-01": [["도료", "오븐"]],
    "EXT-AS-01": [["브레이크", "조향", "에어백", "시트벨트", "연료"]],
    "EXT-AS-02": [["브레이크", "조향", "에어백", "시트벨트", "연료"]],
}
# 용접 설비 교체도 EXT-BD-01 대상 (QS-BD-001 조항 3)
_CONDITION_ALTERNATIVES: dict[str, list[list[str]]] = {
    "EXT-BD-01": [["용접 로봇", "용접건"], ["교체", "신형"]],
}
_FLOW_KEYWORDS = {"FLOW-01": ["강판"], "FLOW-02": ["금형"], "FLOW-03": ["실러", "접착제"],
                  "FLOW-04": ["막두께", "도막 두께"]}


def _section(text: str, title: str) -> str:
    m = re.search(rf"## {re.escape(title)}\n(.*?)(?=\n## |\Z)", text, re.S)
    return m.group(1).strip() if m else ""


def _field(section: str, name: str) -> list[str]:
    m = re.search(rf"^{name}: (.*)$", section, re.M)
    if not m or m.group(1).strip() in ("", "없음"):
        return []
    return [v.strip() for v in m.group(1).split(",") if v.strip()]


def _matches(query: str, groups: list[list[str]]) -> bool:
    return all(any(w in query for w in group) for group in groups)


def _router(user: str) -> str:
    query = _section(user, "변경 요청") or user
    return json.dumps({"route": "review" if re.search(REVIEW_PATTERN, query) else "chat"})


def _classifier(user: str) -> str:
    query = _section(user, "변경 요청")
    return json.dumps({"shop": guess_shop(query), "change_types": guess_change_types(query),
                       "equipment_ids": find_equipment_ids(query),
                       "lines": [l for l in find_lines(query) if l in query]},
                      ensure_ascii=False)


def _planner(user: str) -> str:
    """일부러 불완전한 계획을 낸다 — 검사 기준과 라인 가동 상태를 빠뜨린다.
    권위 게이트(gate_node)가 빠진 필수 task를 코드로 채우는 장면을 결정론적으로 재현한다."""
    c = _section(user, "분류 결과")
    shop = (_field(c, "공장") or [COMMON])[0]
    tasks = [{"kind": "standard", "target": COMMON}]
    if shop != COMMON:
        tasks.append({"kind": "standard", "target": shop})
    tasks += [{"kind": "equipment", "target": eq} for eq in _field(c, "설비")]
    return json.dumps({"tasks": tasks}, ensure_ascii=False)


def _judge(user: str) -> str:
    query = _section(user, "변경 요청")
    item_ids = re.findall(r"^- (EXT-[A-Z]+-\d+) \|", _section(user, "조건부 항목 후보"), re.M)
    flow_ids = re.findall(r"^- (FLOW-\d+) \|", _section(user, "공정 간 영향 후보"), re.M)
    items = [i for i in item_ids
             if (i in _CONDITION_KEYWORDS and _matches(query, _CONDITION_KEYWORDS[i]))
             or (i in _CONDITION_ALTERNATIVES and _matches(query, _CONDITION_ALTERNATIVES[i]))]
    flows = [f for f in flow_ids if any(w in query for w in _FLOW_KEYWORDS.get(f, []))]
    return json.dumps({"applicable_items": list(dict.fromkeys(items)),
                       "applicable_flows": flows})


def _writer(user: str) -> str:
    """Wave 8 재현: 반려 사유가 없는 1차 초안은 의도적으로 저품질(항목 ID 누락) →
    Validator가 반려하면 검증 항목 목록을 빠짐없이 옮긴 2차 초안을 낸다."""
    if "## 검증 반려 사유" not in user:
        return "검토 결과: 표준서대로 진행하면 됩니다."
    summary = _section(user, "변경 요약").replace("\n", ", ")
    items = [l[2:] for l in _section(user, "검증 항목").splitlines() if l.startswith("- [")]
    return (f"1) 변경 요약: {summary} "
            f"2) 검증 항목: {' / '.join(items) or '없음'} "
            "3) 최종 판단과 승인은 품질 담당자가 확인하세요.")


def _chat(user: str) -> str:
    history, query = _section(user, "지금까지의 대화"), _section(user, "사용자의 새 메시지")
    remembered = re.findall(r"제 이름은 (\S+?)입니다", history)
    if remembered and re.search(r"이름이 뭐", query):
        return f"{remembered[-1]}님이라고 말씀하셨어요. 무엇을 도와드릴까요?"
    m = re.search(r"제 이름은 (\S+?)입니다", query)
    if m:
        return f"안녕하세요, {m.group(1)}님! 4M 변경 검토를 도와드릴까요?"
    return "안녕하세요! 4M 변경 검토를 도와드릴까요?"


_AGENTS = {"router": _router, "classifier": _classifier, "planner": _planner,
           "judge": _judge, "writer": _writer, "chat": _chat}


class RuleBasedChatModel(BaseChatModel):
    """시스템 프롬프트의 [agent:이름] 표식으로 응답 규칙을 고르는 결정론 모델."""

    @property
    def _llm_type(self) -> str:
        return "rule-based-4m-fake"

    def _respond(self, messages: list[BaseMessage]) -> str:
        system = str(messages[0].content) if messages else ""
        user = str(messages[-1].content) if messages else ""
        m = re.search(r"\[agent:(\w+)\]", system)
        handler = _AGENTS.get(m.group(1)) if m else None
        return handler(user) if handler else ""

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None,
                  run_manager: CallbackManagerForLLMRun | None = None,
                  **kwargs: Any) -> ChatResult:
        content = self._respond(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])

    def _stream(self, messages: list[BaseMessage], stop: list[str] | None = None,
                run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any):
        # 단어 단위로 쪼개 흘려보낸다 — 실모델처럼 토큰 스트리밍(Wave 3)이 보이게 한다
        for piece in re.findall(r"\S+\s*", self._respond(messages)):
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=piece))
            if run_manager:
                run_manager.on_llm_new_token(piece, chunk=chunk)
            yield chunk
