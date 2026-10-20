"""Agent 구조화 출력 스키마 — LLM이 채우는 결정만 담는다.

LLM이 낸 값은 그대로 믿지 않고 각 Agent가 코드로 보정한다(domain_4m의 목록과 대조).
"""
from typing import Literal

from pydantic import BaseModel, Field

Shop = Literal["프레스", "차체", "도장", "의장"]
ChangeType = Literal["Man", "Machine", "Material", "Method"]
ResearchKind = Literal["standard", "inspection", "equipment", "production"]


class RouteDecision(BaseModel):
    route: Literal["chat", "review"] = Field(
        description="4M 변경 요청·검토·협력사 변경 신고면 review, 인사·잡담·일반 질문이면 chat")


class ChangeClassification(BaseModel):
    shop: Shop | None = Field(description="변경이 일어나는 공장. 요청에서 알 수 없으면 null")
    shop_evidence: str = Field(
        default="", description="공장을 판단한 근거가 된 요청 원문의 구절 (그대로 인용, 없으면 빈 문자열)")
    change_types: list[ChangeType] = Field(
        description="해당하는 변경 유형 전부. 설비 교체와 조건 변경이 함께면 Machine, Method 둘 다")
    equipment_ids: list[str] = Field(default_factory=list,
                                     description="요청에 나온 설비 ID")
    lines: list[str] = Field(default_factory=list, description="요청에 나온 라인 ID")


class ResearchTask(BaseModel):
    kind: ResearchKind
    target: str = Field(description="standard: 공장명 또는 '공통' / inspection: 공장명 / "
                                    "equipment: 설비 ID 또는 라인 ID / production: 라인 ID")


class ResearchPlan(BaseModel):
    tasks: list[ResearchTask]


class CandidateDecision(BaseModel):
    id: str = Field(description="후보 ID (EXT-… 또는 FLOW-…)")
    applies: bool = Field(description="변경 요청이 이 후보의 조건에 해당하면 true")
    reason: str = Field(description="한 문장 근거")


class ConditionDecisions(BaseModel):
    """후보마다 하나씩 판정한다 — 해당하는 ID만 고르게 하면 소형 모델이 후보를 건너뛰고
    놓치는 일이 많았다 (판정 단독 실험: Recall 0.45 → 0.82, 과잉 판정 0)."""
    decisions: list[CandidateDecision]
