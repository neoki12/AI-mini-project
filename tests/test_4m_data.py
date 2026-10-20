"""4M 도메인 데이터 정합성 테스트 — LLM 없이 도는 결정론적 검사.

규칙표, 표준서, 공정 흐름, 설비·생산 데이터, 평가 데이터셋이 서로 어긋나지 않는지 확인한다.
데이터를 고친 뒤에는 eval/build_4m_dataset.py를 다시 실행하고 이 테스트를 돌린다.

실행:
    python3 -m pytest tests/test_4m_data.py -q     # pytest가 있을 때
    python3 tests/test_4m_data.py                  # pytest 없이
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "4m"
sys.path.insert(0, str(ROOT))

from eval.build_4m_dataset import build, required_items_for  # noqa: E402

CHANGE_TYPES = {"Man", "Machine", "Material", "Method"}
SHOPS = {"프레스", "차체", "도장", "의장"}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_docs() -> dict[str, dict]:
    """doc_id → {"front": front-matter dict, "clauses": {번호: 본문}}"""
    docs = {}
    for path in sorted((DATA / "standards").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        assert m, f"front-matter 없음: {path.name}"
        front = dict(line.split(": ", 1) for line in m.group(1).splitlines())
        clauses = {}
        for cm in re.finditer(r"^## 조항 (\S+) [^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M):
            clauses[cm.group(1)] = cm.group(2)
        docs[front["doc_id"]] = {"front": front, "clauses": clauses, "file": path.name}
    return docs


RULES = _json(DATA / "rules" / "required_items.json")
FLOW = _json(DATA / "process_flow.json")
EQUIPMENT = _json(DATA / "equipment.json")["equipment"]
PRODUCTION = _json(DATA / "production.json")["lines"]
DOCS = _load_docs()
CASES = build()


def test_rule_items_exist():
    for ct, items in RULES["rules"].items():
        assert ct in CHANGE_TYPES, ct
        for item in items:
            assert item in RULES["items"], f"{ct} 규칙의 {item}이 items에 없음"


def test_docs_front_matter_and_chunk_count():
    for doc_id, d in DOCS.items():
        for key in ("doc_id", "title", "rev", "shop", "doc_type", "change_types"):
            assert key in d["front"], f"{d['file']}: front-matter에 {key} 없음"
        assert d["clauses"], f"{d['file']}: 조항이 없음"
    total = sum(len(d["clauses"]) for d in DOCS.values())
    assert total >= 30, f"조항 청크 {total}개 — RAG 비교에는 30개 이상 필요"


def test_flow_rules_reference_known_items():
    for rule in FLOW["rules"]:
        assert rule["from_shop"] in SHOPS
        assert rule["change_type"] in CHANGE_TYPES
        for item in rule["items"]:
            assert item in FLOW["items"], f"{rule['id']}의 {item}이 flow items에 없음"


def test_required_items_union():
    assert required_items_for(["Machine", "Method"], RULES["rules"]) == sorted(
        set(RULES["rules"]["Machine"]) | set(RULES["rules"]["Method"]))


def test_cases_basic_fields():
    assert len(CASES) == 10
    for case in CASES:
        exp = case["expected"]
        assert exp["shop"] in SHOPS, case["id"]
        assert set(exp["change_types"]) <= CHANGE_TYPES, case["id"]
        assert exp["change_grade"] in RULES["grades"], case["id"]
        for doc_id in exp["relevant_docs"]:
            assert doc_id in DOCS, f"{case['id']}: {doc_id} 문서 없음"


def test_cases_cover_all_change_types_and_shops():
    types = {ct for c in CASES for ct in c["expected"]["change_types"]}
    shops = {c["expected"]["shop"] for c in CASES}
    assert types == CHANGE_TYPES
    assert shops == SHOPS
    assert sum(len(c["expected"]["change_types"]) > 1 for c in CASES) >= 2, "복합 변경 2건 이상"


def test_every_extra_and_downstream_item_has_valid_evidence():
    flow_rules = {r["id"]: r for r in FLOW["rules"]}
    for case in CASES:
        exp = case["expected"]
        for item in exp["extra_items"] + exp["downstream_items"]:
            ev = exp["evidence"].get(item)
            assert ev, f"{case['id']}: {item} 근거 없음"
            if "flow_rule" in ev:
                rule = flow_rules[ev["flow_rule"]]
                assert item in rule["items"], f"{case['id']}: {ev['flow_rule']}에 {item} 없음"
                assert rule["from_shop"] == exp["shop"], f"{case['id']}: 출발 공장 불일치"
                assert rule["change_type"] in exp["change_types"], f"{case['id']}: 유형 불일치"
                continue
            d = DOCS[ev["doc_id"]]
            clause = d["clauses"].get(ev["clause"])
            assert clause, f"{case['id']}: {ev['doc_id']} 조항 {ev['clause']} 없음"
            assert item in clause, f"{case['id']}: {ev['doc_id']} 조항 {ev['clause']}에 {item} 표기 없음"
            assert ev["doc_id"] in exp["relevant_docs"], f"{case['id']}: 근거 문서가 relevant_docs에 없음"
            if ev.get("tool") == "equipment":
                for eq in ev["ids"]:
                    assert EQUIPMENT[eq]["abnormal"], f"{case['id']}: {eq}가 이상 상태가 아님"
            if ev.get("tool") == "production":
                for line in ev["ids"]:
                    assert PRODUCTION[line]["status"] == "running", f"{case['id']}: {line} 비가동"


def test_extra_items_are_not_in_rule_table():
    """extra_items가 규칙표에 있으면 게이트만으로 맞힐 수 있어 순환 측정이 된다."""
    rule_items = set(RULES["items"])
    for case in CASES:
        for item in case["expected"]["extra_items"]:
            assert item not in rule_items, f"{case['id']}: {item}이 규칙표에 있음"


def test_grade_consistency():
    for case in CASES:
        exp = case["expected"]
        safety = any(i.startswith("EXT-AS-") for i in exp["extra_items"])
        if safety:
            expected = "A"
        elif set(exp["change_types"]) == {"Man"}:
            expected = "C"
        else:
            expected = "B"
        assert exp["change_grade"] == expected, f"{case['id']}: 등급 {exp['change_grade']} ≠ {expected}"


def test_dataset_file_matches_builder():
    path = ROOT / "eval" / "4m_dataset.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert rows == CASES, "4m_dataset.jsonl이 오래됨 — python3 eval/build_4m_dataset.py 재실행"


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in globals().items() if name.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
