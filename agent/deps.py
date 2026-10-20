"""Wave 13 — 의존성 주입.

노드 함수가 closure의 지역 변수에 암묵적으로 기대지 않도록, supervisor가 쓰는 모든
의존성을 SupervisorDeps 하나에 명시적으로 담아 functools.partial로 각 노드에 주입한다.
파일을 어디로 옮겨도, 단위 테스트에서 mock deps로 갈아 끼워도 동작이 같다.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Features:
    """기능 스위치 — 전부 끄면 Baseline(Before), 전부 켜면 Improved(After).

    하나씩만 켜서 돌리면 개선 항목별 기여도를 분리해 측정할 수 있다."""
    gate_4m: bool = True            # 규칙표 필수 항목 + 필수 조사 task를 코드가 강제
    judge_conditions: bool = True   # 조건부 조항을 Agent가 판정 (끄면 문서의 모든 항목 나열)
    flow_impact: bool = True        # 다음 공정 영향(DS-*) 도출
    validator_4m: bool = True       # 항목 누락 탐지 (끄면 길이·번호만 보는 범용 검증)
    rag: bool = True                # 표준서 조항 RAG 검색 (끄면 공장 문서 전체를 키워드 매핑으로 읽음)

    @classmethod
    def baseline(cls) -> "Features":
        return cls(gate_4m=False, judge_conditions=False, flow_impact=False,
                   validator_4m=False, rag=False)


@dataclass
class SupervisorDeps:
    fast_llm: Any        # Wave 10a — 라우팅·분류·계획·판정용 저비용 모델 (LLMHandle)
    quality_llm: Any     # Wave 10a — 최종 보고 작성용 고품질 모델 (LLMHandle)
    mcp: Any             # Wave 2  — MCP stdio 클라이언트 (Tool/Resource/Prompt)
    session_store: Any   # Wave 12 — SQLite 세션 저장소
    version: str         # Wave 14 — SUPERVISOR_VERSION (v1/v2)
    features: Features = field(default_factory=Features)
    judge_llm: Any = None   # 조건 판정 전용 모델 (없으면 fast_llm). 판정은 등급·항목을 정하는 핵심
                            # 단계라 quality 모델을 쓴다 — 실험: qwen2.5:7b 10/11 → qwen3:8b 11/11
