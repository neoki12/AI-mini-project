"""홀드아웃 평가 데이터셋 — eval/4m_holdout.jsonl을 만든다.

개발 중에 한 번도 쓰지 않은 표현으로 쓴 요청 10건이다. 개발 데이터셋(4m_dataset.jsonl)은
결과를 보면서 분류 키워드와 판정 방식을 고쳤기 때문에 점수가 높게 나오기 쉽다. 이 데이터셋은
시스템 출력을 보기 전에 정답을 확정하고, 결과를 본 뒤에도 시스템 코드를 고치지 않은 상태로
한 번만 측정한다 (정답은 표준서·규칙표·현장 데이터만으로 정한다).

정답 규칙은 개발 데이터셋과 같다 (required_items는 규칙표에서 자동 계산).

    python3 eval/build_4m_holdout.py
"""
import json
from pathlib import Path

from build_4m_dataset import RULES_PATH, doc, required_items_for

OUT_PATH = Path(__file__).resolve().parent / "4m_holdout.jsonl"

CASES = [
    {
        "id": "hold-01",
        "input": "페인트샵 상도 부스 교대 인원 2명을 신규 채용 인력으로 바꿉니다.",
        "shop": "도장", "change_types": ["Man"], "change_grade": "C",
        "extra_items": [], "downstream_items": [], "evidence": {},
        "relevant_docs": ["QS-CM-001", "QS-PT-001"],
        "probe": "'페인트샵'(외래어)으로 도장 공장을 알아보는가",
    },
    {
        "id": "hold-02",
        "input": "상도 클리어 도막을 40㎛에서 35㎛로 줄이는 사양 변경을 검토하고 있어요.",
        "shop": "도장", "change_types": ["Method"], "change_grade": "B",
        "extra_items": [], "downstream_items": ["DS-AS-01"],
        "evidence": {"DS-AS-01": {"flow_rule": "FLOW-04"}},
        "relevant_docs": ["QS-CM-001", "QS-PT-001"],
        "probe": "공장명 없이 '상도 클리어 도막'만으로 도장·Method와 다음 공정(의장) 영향을 찾는가",
    },
    {
        "id": "hold-03",
        "input": "중도 도료 납품 업체를 바꿉니다. 색상과 사양은 같고 제조사만 달라져요.",
        "shop": "도장", "change_types": ["Material"], "change_grade": "B",
        "extra_items": ["EXT-PT-01"], "downstream_items": [],
        "evidence": {"EXT-PT-01": doc("QS-PT-001", "4")},
        "relevant_docs": ["QS-CM-001", "QS-PT-001"],
        "probe": "'납품 업체'를 공급사 변경으로 보고 도료 공급사 조건(EXT-PT-01)을 적용하는가",
    },
    {
        "id": "hold-04",
        "input": "프레스 1라인 보닛 겉판 금형을 새로 깎아서 교체할 예정입니다.",
        "shop": "프레스", "change_types": ["Machine"], "change_grade": "B",
        "extra_items": ["EXT-PR-01"], "downstream_items": ["DS-BD-02"],
        "evidence": {"EXT-PR-01": doc("QS-PR-001", "3"), "DS-BD-02": {"flow_rule": "FLOW-02"}},
        "relevant_docs": ["QS-CM-001", "QS-PR-001"],
        "probe": "'보닛 겉판'을 외판으로 이해해 외판 금형 조건과 패널 형상 영향을 찾는가",
    },
    {
        "id": "hold-05",
        "input": "도어 아우터용 GA 코일을 지금 쓰는 제철소 말고 다른 제철소 제품으로 받으려고 합니다.",
        "shop": "프레스", "change_types": ["Material"], "change_grade": "B",
        "extra_items": [], "downstream_items": ["DS-BD-01", "DS-PT-01"],
        "evidence": {"DS-BD-01": {"flow_rule": "FLOW-01"}, "DS-PT-01": {"flow_rule": "FLOW-01"}},
        "relevant_docs": ["QS-CM-001", "QS-PR-001"],
        "probe": "강판 공급사 변경을 '코일·제철소'로 표현해도 차체·도장 영향을 찾는가",
    },
    {
        "id": "hold-06",
        "input": "플로어 쪽 실링에 쓰는 실러를 다른 회사 제품으로 바꿔요. 이번 주말 특근 때 바로 적용할게요.",
        "shop": "차체", "change_types": ["Material"], "change_grade": "B",
        "extra_items": ["EXT-LOT-01"], "downstream_items": ["DS-PT-02"],
        "evidence": {"EXT-LOT-01": {**doc("QS-CM-001", "5"), "tool": "production", "ids": ["BD-FLOOR"]},
                     "DS-PT-02": {"flow_rule": "FLOW-03"}},
        "relevant_docs": ["QS-CM-001", "QS-BD-001"],
        "probe": "차체 실러(도장 실링 아님)로 보고, 라인 ID 없이 '플로어'로 가동 중 라인을 찾는가",
    },
    {
        "id": "hold-07",
        "input": "의장 1라인 스티어링 컬럼 체결용 너트러너를 새 모델로 바꾸고 체결 토크 값도 조정합니다.",
        "shop": "의장", "change_types": ["Machine", "Method"], "change_grade": "A",
        "extra_items": ["EXT-AS-01", "EXT-AS-02"], "downstream_items": [],
        "evidence": {"EXT-AS-01": doc("QS-AS-001", "3"), "EXT-AS-02": doc("QS-AS-001", "3")},
        "relevant_docs": ["QS-CM-001", "QS-AS-001"],
        "probe": "'스티어링'을 조향(안전 체결부)으로 알아보고 A등급으로 올리는가",
    },
    {
        "id": "hold-08",
        "input": "라디에이터 그릴 가니쉬 납품처를 바꿉니다.",
        "shop": "의장", "change_types": ["Material"], "change_grade": "B",
        "extra_items": [], "downstream_items": [], "evidence": {},
        "relevant_docs": ["QS-CM-001", "QS-AS-001"],
        "probe": "공장명 없이 부품명만으로 의장 공장을 알아보는가",
    },
    {
        "id": "hold-09",
        "input": "리어 콤비 램프(후미등) 공급처를 변경합니다. 의장 공장 기준으로 봐 주세요.",
        "shop": "의장", "change_types": ["Material"], "change_grade": "A",
        "extra_items": [], "downstream_items": [], "evidence": {},
        "relevant_docs": ["QS-CM-001", "QS-AS-001"],
        "probe": "규칙표 목록에 없는 '후미등'을 법규 관련 부품(등화장치)으로 보고 A등급을 주는가",
    },
    {
        "id": "hold-10",
        "input": "BD-SIDE 라인 스폿건 2대를 서보건으로 바꿀 예정입니다.",
        "shop": "차체", "change_types": ["Machine"], "change_grade": "B",
        "extra_items": ["EXT-BD-01"], "downstream_items": [],
        "evidence": {"EXT-BD-01": doc("QS-BD-001", "3")},
        "relevant_docs": ["QS-CM-001", "QS-BD-001"],
        "probe": "'스폿건→서보건'을 용접건 교체로 보고 파괴 검사 조건을 적용하는가",
    },
]


def build() -> list[dict]:
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))["rules"]
    out = []
    for case in CASES:
        expected = {
            "shop": case["shop"], "change_types": case["change_types"],
            "change_grade": case["change_grade"],
            "required_items": required_items_for(case["change_types"], rules),
            "extra_items": case["extra_items"], "downstream_items": case["downstream_items"],
            "evidence": case["evidence"], "relevant_docs": case["relevant_docs"],
        }
        out.append({"id": case["id"], "input": case["input"], "expected": expected,
                    "trap": case["probe"]})
    return out


if __name__ == "__main__":
    rows = build()
    OUT_PATH.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"{OUT_PATH.name}: {len(rows)}건")
