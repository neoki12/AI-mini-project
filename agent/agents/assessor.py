"""Assessor (코드) — 검증 항목 체크리스트, 변경 등급, 초기유동관리를 정한다.

체크리스트는 네 층으로 구성한다 (data/4m/README.md "정답의 세 층" + 공정 간 영향).
- required   : 규칙표(①) — gate_4m=True일 때만
- document   : 표준서 조건부 조항(②) — judge가 해당한다고 판정한 것
- field      : 현장 데이터(③) — Field Data Agent가 Tool 결과로 판정한 것
- downstream : 다음 공정 영향 — judge가 해당한다고 판정한 공정 흐름 규칙의 DS-* 항목

변경 등급(QS-CM-001 조항 2): 안전 체결부 항목(EXT-AS-*)이 걸리면 A, Man 단독이면 C,
그 밖은 B. 등급을 잘못 낮추면 승인 절차를 건너뛰게 되므로 판단 근거를 함께 남긴다.
"""
from ..domain_4m import (APPROVER, INITIAL_FLOW_PERIOD, RULES, item_name,
                         required_items)


def build_checklist(classification: dict, judged: dict, field: list[dict],
                    *, gate_4m: bool) -> list[dict]:
    checklist, seen = [], set()

    def add(item: dict) -> None:
        if item["id"] not in seen:
            seen.add(item["id"])
            checklist.append(item)

    if gate_4m:
        for item_id in required_items(classification["change_types"]):
            add({"id": item_id, "name": item_name(item_id), "layer": "required",
                 "evidence": {"rule": "required_items.json",
                              "rule_version": RULES.get("version"),
                              "change_types": classification["change_types"]}})
    for c in judged["items"]:
        is_rule_item = c["id"] in RULES.get("items", {})
        add({"id": c["id"],
             "name": item_name(c["id"]) if is_rule_item else c["clause_title"],
             "layer": "document",
             "evidence": {"doc_id": c["doc_id"], "rev": c["rev"], "clause": c["clause"],
                          "clause_title": c["clause_title"]}})
    for item in field:
        add(item)
    for rule in judged["flows"]:
        for item_id in rule["items"]:
            add({"id": item_id, "name": item_name(item_id), "layer": "downstream",
                 "evidence": {"flow_rule": rule["id"], "subject": rule["subject"]}})
    return checklist


def grade(classification: dict, checklist: list[dict]) -> dict:
    safety = [i["id"] for i in checklist if i["id"].startswith("EXT-AS-")]
    if safety:
        level, reason = "A", f"안전 체결부 항목 {', '.join(safety)} 해당 (QS-AS-001 조항 2)"
    elif classification["change_types"] == ["Man"]:
        level, reason = "C", "Man 단독 변경 (QS-CM-001 조항 2)"
    else:
        level, reason = "B", "A등급이 아닌 Machine·Material·Method 변경 (QS-CM-001 조항 2)"
    return {"grade": level, "approver": APPROVER[level],
            "initial_flow_period": INITIAL_FLOW_PERIOD[level], "reason": reason}
