"""4M 검토 채점 함수 — 체크리스트 항목 ID 기준 Recall·Precision·F1.

정답은 eval/4m_dataset.jsonl의 expected (required_items + extra_items + downstream_items).
층별 Recall은 각 개선의 효과를 분리해서 보여 준다 (data/4m/README.md "정답의 세 층").
Recall만 보면 항목을 다 나열해도 만점이므로 Precision과 F1을 함께 본다.
"""
FIELD_ITEMS = {"EXT-EQ-01", "EXT-LOT-01"}


def expected_layers(expected: dict) -> dict[str, set[str]]:
    extra = set(expected["extra_items"])
    return {
        "required": set(expected["required_items"]),
        "document": extra - FIELD_ITEMS,
        "field": extra & FIELD_ITEMS,
        "downstream": set(expected["downstream_items"]),
    }


def _ratio(hit: int, total: int) -> float | None:
    return round(hit / total, 4) if total else None


def score(predicted_ids: set[str], expected: dict) -> dict:
    layers = expected_layers(expected)
    gold = set().union(*layers.values())
    hit = predicted_ids & gold
    recall = _ratio(len(hit), len(gold))
    precision = _ratio(len(hit), len(predicted_ids))
    f1 = (round(2 * recall * precision / (recall + precision), 4)
          if recall and precision else 0.0)
    return {
        "recall": recall, "precision": precision, "f1": f1,
        "recall_by_layer": {name: _ratio(len(predicted_ids & ids), len(ids))
                            for name, ids in layers.items()},
        "missing": sorted(gold - predicted_ids),
        "extra": sorted(predicted_ids - gold),
    }


def mean(values: list[float | None]) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 4) if values else None
