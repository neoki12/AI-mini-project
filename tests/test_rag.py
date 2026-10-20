"""RAG 인덱스 단위 테스트 — fake 임베딩(결정론)과 메모리 인덱스로 청크·필터·재인덱싱을 확인한다."""
import json
import shutil
from pathlib import Path

import pytest

from rag.index import FakeEmbedder, StandardsIndex, load_chunks

ROOT = Path(__file__).resolve().parent.parent
DATASET = [json.loads(line) for line in (ROOT / "eval" / "4m_dataset.jsonl")
           .read_text(encoding="utf-8").splitlines() if line]


@pytest.fixture(scope="module")
def index():
    return StandardsIndex(FakeEmbedder(), index_dir=None)


def test_chunks_are_clauses_with_metadata():
    chunks = load_chunks()
    assert len(chunks) == 41
    first = next(c for c in chunks if c["id"] == "QS-BD-001#3")
    assert first["metadata"] | {"doc_type": "standard", "shop": "차체", "ct_Method": True,
                                "ct_Man": False} == first["metadata"]


def test_fake_embedder_is_deterministic_and_normalized():
    a, b = FakeEmbedder().embed(["용접 전류 조건 변경"] * 2)
    assert a == b and abs(sum(v * v for v in a) - 1.0) < 1e-9


@pytest.mark.parametrize("case", DATASET, ids=[c["id"] for c in DATASET])
def test_top4_contains_every_conditional_clause(index, case):
    """평가 10건에서 조건부 항목의 근거 조항(공통 규정 제외)이 상위 4개 안에 든다."""
    exp = case["expected"]
    hits = index.search(case["input"], exp["shop"], exp["change_types"], k=4)
    got = {(h["doc_id"], h["clause"]) for h in hits}
    for item, ev in exp["evidence"].items():
        if "doc_id" in ev and not ev["doc_id"].startswith("QS-CM"):
            assert (ev["doc_id"], ev["clause"]) in got, item


def test_filters_exclude_other_shops_and_common(index):
    hits = index.search("실러 도포 위치와 경화 조건", shop="도장", change_types=["Material"], k=10)
    assert hits and {h["shop"] for h in hits} == {"도장"}
    with_common = index.search("초기유동관리 기간", shop="도장", change_types=["Man"], k=10,
                               include_common=True)
    assert "공통" in {h["shop"] for h in with_common}


def test_persistent_index_rebuilds_when_standards_change(tmp_path):
    standards = tmp_path / "standards"
    shutil.copytree(ROOT / "data" / "4m" / "standards", standards)
    first = StandardsIndex(FakeEmbedder(), index_dir=tmp_path / "idx", standards_dir=standards)
    first.ensure()
    assert first.rebuilt is True
    again = StandardsIndex(FakeEmbedder(), index_dir=tmp_path / "idx", standards_dir=standards)
    again.ensure()
    assert again.rebuilt is False                     # 내용이 같으면 재사용
    doc = standards / "QS-PT-001_paint_process.md"
    doc.write_text(doc.read_text(encoding="utf-8").replace("rev: D", "rev: E"), encoding="utf-8")
    revised = StandardsIndex(FakeEmbedder(), index_dir=tmp_path / "idx", standards_dir=standards)
    revised.ensure()
    assert revised.rebuilt is True                    # 개정되면 다시 인덱싱
    assert {h["rev"] for h in revised.search("도료 변경", shop="도장", k=10)
            if h["doc_id"] == "QS-PT-001"} == {"E"}
