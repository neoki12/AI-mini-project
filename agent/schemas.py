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
    shop: Shop | None = Field(description="변경이 일어나는 공장")
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


class ConditionDecision(BaseModel):
    applicable_items: list[str] = Field(
        default_factory=list, description="이번 변경 요청에 실제로 해당하는 조건부 항목 ID")
    applicable_flows: list[str] = Field(
        default_factory=list, description="이번 변경 요청에 실제로 해당하는 공정 간 영향 규칙 ID")
