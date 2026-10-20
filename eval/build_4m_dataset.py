"""4M 평가 데이터셋 생성기 — eval/4m_dataset.jsonl을 만든다.

정답의 세 층을 구분한다.
- required_items  : 규칙표(data/4m/rules/required_items.json)에서 change_types로 자동 계산
                    → 손으로 적지 않는다 (오타로 채점이 틀어지는 것 방지)
- extra_items     : 표준서 조건부 조항(② 문서 근거) 또는 Tool 데이터(③ 현장 데이터)에서만
                    알 수 있는 항목. 규칙표에는 없다.
- downstream_items: 공정 흐름(data/4m/process_flow.json)에 따른 다음 공장 확인 항목

각 extra/downstream 항목에는 evidence(근거)를 붙인다. tests/test_4m_data.py가 근거가
실제 데이터에 존재하는지 검사한다.

실행:
    python3 eval/build_4m_dataset.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = ROOT / "data" / "4m" / "rules" / "required_items.json"
OUT_PATH = Path(__file__).resolve().parent / "4m_dataset.jsonl"


def doc(doc_id: str, clause: str) -> dict:
    return {"doc_id": doc_id, "clause": clause}


CASES = [
    {
        "id": "case-01",
        "input": "의장 2라인(AS-2) 야간조 도어 트림 장착 공정에 신입 작업자 4명을 투입하려고 합니다. 4M 검토 부탁드립니다.",
        "shop": "의장",
        "change_types": ["Man"],
        "change_grade": "C",
        "extra_items": [],
        "downstream_items": [],
        "evidence": {},
        "relevant_docs": ["QS-CM-001", "QS-AS-001"],
        "trap": "같은 라인의 AS-NR-120(크래시패드 공정)이 교정 기한 만료지만 도어 트림 공정과 무관 → EXT-EQ-01을 넣으면 Precision 감점",
    },
    {
        "id": "case-02",
        "input": "도장 공장 수작업 실링 담당자를 다른 공정 작업자로 전환 배치해 교체합니다. 검토해주세요.",
        "shop": "도장",
        "change_types": ["Man"],
        "change_grade": "C",
        "extra_items": [],
        "downstream_items": [],
        "evidence": {},
        "relevant_docs": ["QS-CM-001", "QS-PT-001"],
        "trap": "차체 실러(QS-BD-001)와 도장 실링(QS-PT-001)을 혼동하기 쉬움",
    },
    {
        "id": "case-03",
        "input": "차체 공장 사이드 패널 라인의 용접 로봇 BD-RB-201, BD-RB-202 2대를 신형 모델로 교체합니다. 필요한 검증 항목을 알려주세요.",
        "shop": "차체",
        "change_types": ["Machine"],
        "change_grade": "B",
        "extra_items": ["EXT-BD-01"],
        "downstream_items": [],
        "evidence": {"EXT-BD-01": doc("QS-BD-001", "3")},
        "relevant_docs": ["QS-CM-001", "QS-BD-001"],
        "trap": "정기 파괴 검사(QS-BD-002 조항 2)는 변경 시 파괴 검사를 대신하지 않음",
    },
    {
        "id": "case-04",
        "input": "프레스 1라인 후드 외판 드로잉 금형(PR-DIE-HD01)을 수정하려고 합니다. 4M 영향 검토 부탁드립니다.",
        "shop": "프레스",
        "change_types": ["Machine"],
        "change_grade": "B",
        "extra_items": ["EXT-PR-01"],
        "downstream_items": ["DS-BD-02"],
        "evidence": {
            "EXT-PR-01": doc("QS-PR-001", "3"),
            "DS-BD-02": {"flow_rule": "FLOW-02"},
        },
        "relevant_docs": ["QS-CM-001", "QS-PR-001"],
        "trap": "같은 프레스 공장의 case-05(Material)와 change_type이 다름",
    },
    {
        "id": "case-05",
        "input": "루프 패널용 강판의 공급사를 기존 X제철에서 Y제철로 변경합니다. 재질과 두께 사양은 동일합니다. 검토해주세요.",
        "shop": "프레스",
        "change_types": ["Material"],
        "change_grade": "B",
        "extra_items": [],
        "downstream_items": ["DS-BD-01", "DS-PT-01"],
        "evidence": {
            "DS-BD-01": {"flow_rule": "FLOW-01"},
            "DS-PT-01": {"flow_rule": "FLOW-01"},
        },
        "relevant_docs": ["QS-CM-001", "QS-PR-001"],
        "trap": "사양이 동일해도 공급사 변경이면 다음 공정 영향 검토 대상",
    },
    {
        "id": "case-06",
        "input": "협력사로부터 브레이크 호스 브래킷 부품의 4M 변경 신고(생산 공장 이전)가 접수됐습니다. 의장 공장 기준으로 검토해주세요.",
        "shop": "의장",
        "change_types": ["Material"],
        "change_grade": "A",
        "extra_items": ["EXT-AS-01", "EXT-AS-02"],
        "downstream_items": [],
        "evidence": {
            "EXT-AS-01": doc("QS-AS-001", "3"),
            "EXT-AS-02": doc("QS-AS-001", "3"),
        },
        "relevant_docs": ["QS-CM-001", "QS-AS-001"],
        "trap": "'브레이크'가 안전 체결부(QS-AS-001 조항 2)임을 놓치면 등급과 EXT 항목을 모두 놓침",
    },
    {
        "id": "case-07",
        "input": "도장 공장 상도 건조 오븐(PT-OV-02)의 온도 프로파일을 에너지 절감을 위해 변경하려고 합니다. 검토 부탁드립니다.",
        "shop": "도장",
        "change_types": ["Method"],
        "change_grade": "B",
        "extra_items": ["EXT-PT-01"],
        "downstream_items": [],
        "evidence": {"EXT-PT-01": doc("QS-PT-001", "4")},
        "relevant_docs": ["QS-CM-001", "QS-PT-001"],
        "trap": "오븐은 도장 공장 안의 설비라 DS-PT-02(차체 실러 변경 시 항목)는 해당 없음",
    },
    {
        "id": "case-08",
        "input": "차체 대시 패널 라인 용접 로봇(BD-RB-301, BD-RB-302)의 용접 전류 조건을 변경합니다. 필요한 검증 항목을 알려주세요.",
        "shop": "차체",
        "change_types": ["Method"],
        "change_grade": "B",
        "extra_items": ["EXT-BD-01", "EXT-EQ-01"],
        "downstream_items": [],
        "evidence": {
            "EXT-BD-01": doc("QS-BD-001", "3"),
            "EXT-EQ-01": {**doc("QS-CM-001", "4"),
                          "tool": "equipment", "ids": ["BD-RB-301", "BD-RB-302"]},
        },
        "relevant_docs": ["QS-CM-001", "QS-BD-001"],
        "trap": "계속 사용하는 로봇의 팁 교체 주기 초과를 Tool로 확인해야 EXT-EQ-01을 찾음",
    },
    {
        "id": "case-09",
        "input": "의장 1라인 시트벨트 앵커 체결 너트러너(AS-NR-305)를 신형으로 교체하면서 체결 토크 사양도 함께 변경합니다. 4M 검토해주세요.",
        "shop": "의장",
        "change_types": ["Machine", "Method"],
        "change_grade": "A",
        "extra_items": ["EXT-AS-01", "EXT-AS-02"],
        "downstream_items": [],
        "evidence": {
            "EXT-AS-01": doc("QS-AS-001", "3"),
            "EXT-AS-02": doc("QS-AS-001", "3"),
        },
        "relevant_docs": ["QS-CM-001", "QS-AS-001"],
        "trap": "복합 변경(Machine+Method) — 두 유형 규칙의 합집합 필요",
    },
    {
        "id": "case-10",
        "input": "차체 플로어 라인(BD-FLOOR)에 신규 용접 지그를 도입하고, 같은 시점에 구조용 접착제를 B사 제품으로 변경합니다. 이번 주말에 적용할 예정입니다.",
        "shop": "차체",
        "change_types": ["Machine", "Material"],
        "change_grade": "B",
        "extra_items": ["EXT-LOT-01"],
        "downstream_items": ["DS-PT-02"],
        "evidence": {
            "EXT-LOT-01": {**doc("QS-CM-001", "5"),
                           "tool": "production", "ids": ["BD-FLOOR"]},
            "DS-PT-02": {"flow_rule": "FLOW-03"},
        },
        "relevant_docs": ["QS-CM-001", "QS-BD-001"],
        "trap": "주말이지만 BD-FLOOR는 특근 가동 중 — Tool로 확인해야 EXT-LOT-01을 찾음",
    },
]


def required_items_for(change_types: list[str], rules: dict) -> list[str]:
    """복합 변경이면 유형별 규칙의 합집합 (중복 제거, 정렬)."""
    items: set[str] = set()
    for ct in change_types:
        items.update(rules[ct])
    return sorted(items)


def build() -> list[dict]:
    rules = json.loads(RULES_PATH.read_text())["rules"]
    rows = []
    for case in CASES:
        expected = {
            "shop": case["shop"],
            "change_types": case["change_types"],
            "change_grade": case["change_grade"],
            "required_items": required_items_for(case["change_types"], rules),
            "extra_items": case["extra_items"],
            "downstream_items": case["downstream_items"],
            "evidence": case["evidence"],
            "relevant_docs": case["relevant_docs"],
        }
        rows.append({"id": case["id"], "input": case["input"],
                     "expected": expected, "trap": case["trap"]})
    return rows


if __name__ == "__main__":
    rows = build()
    with OUT_PATH.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"생성됨: {OUT_PATH.relative_to(ROOT)} ({len(rows)}건)")
