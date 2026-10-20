"""Validator (코드) — 초안을 검사하고 검토 상태를 정한다 (Wave 8).

- validator_4m=True : 체크리스트의 모든 항목 ID가 [ID] 형태로 초안에 있어야 합격.
  3회 시도 후에도 빠지면 강제로 통과시키지 않고 review_status="추가 확인 필요"로 내보낸다.
  해당 공장의 공정 표준을 찾지 못한 경우(Partial Result)도 "추가 확인 필요"다.
- validator_4m=False (Baseline): Base의 범용 기준(30자 이상 + 번호 형식), 3회 후 통과 처리.
"""
MAX_ATTEMPTS = 3
DONE, NEEDS_CHECK = "검토 완료", "추가 확인 필요"


def validate(draft: str, checklist: list[dict], warnings: list[str], attempts: int,
             *, validator_4m: bool) -> dict:
    """{"ok", "verdict", "feedback", "missing", "review_status"}. ok=False면 재작성."""
    if not validator_4m:
        ok = len(draft) >= 30 and "1)" in draft
        if ok:
            return {"ok": True, "verdict": "합격", "feedback": None, "missing": [],
                    "review_status": DONE}
        if attempts >= MAX_ATTEMPTS:   # 실모델 무한 재작성 방지 — Base 동작 그대로
            return {"ok": True, "verdict": "합격(최대 시도 도달 — 통과 처리)",
                    "feedback": None, "missing": [], "review_status": DONE}
        return {"ok": False, "verdict": "불합격", "missing": [], "review_status": None,
                "feedback": (f"응답이 너무 짧습니다({len(draft)}자, 최소 30자). 검토 결과를 "
                             "1) 2) 3) 번호로 구체적으로 작성하세요.")}

    missing = [i["id"] for i in checklist if f"[{i['id']}]" not in draft]
    if not missing:
        status = NEEDS_CHECK if warnings else DONE
        return {"ok": True, "verdict": "합격", "feedback": None, "missing": [],
                "review_status": status}
    if attempts >= MAX_ATTEMPTS:
        return {"ok": True, "verdict": "누락 남음 — 추가 확인 필요", "feedback": None,
                "missing": missing, "review_status": NEEDS_CHECK}
    return {"ok": False, "verdict": "불합격", "missing": missing, "review_status": None,
            "feedback": ("다음 검증 항목이 보고서에 빠졌습니다. 각 항목을 [ID] 형태로 근거와 함께 "
                         f"모두 포함하세요: {', '.join(missing)}")}
