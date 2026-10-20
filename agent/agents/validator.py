"""Validator (코드) — 초안을 검사하고 검토 상태를 정한다 (Wave 8).

- validator_4m=True : 체크리스트의 모든 항목 ID가 [ID] 형태로 초안에 있어야 하고, 초안의 인용이
  실제 데이터와 맞아야 합격 (근거 인용 검증 — 계획서 9번):
  · 체크리스트에 없는 항목 ID를 인용하지 않았는가 (지어낸 항목)
  · 인용한 문서를 실제로 읽었는가, 그 문서에 그 조항이 있는가, 개정판이 맞는가
  3회 시도 후에도 문제가 남으면 강제로 통과시키지 않고 review_status="추가 확인 필요"로 내보낸다.
  해당 공장의 공정 표준을 찾지 못한 경우(Partial Result)도 "추가 확인 필요"다.
- validator_4m=False (Baseline): Base의 범용 기준(30자 이상 + 번호 형식), 3회 후 통과 처리.
"""
import re

from ..domain_4m import ITEM_ID_PATTERN, standards_index

MAX_ATTEMPTS = 3
DONE, NEEDS_CHECK = "검토 완료", "추가 확인 필요"


def validate(draft: str, checklist: list[dict], warnings: list[str], attempts: int,
             *, validator_4m: bool, documents: list[dict] | None = None) -> dict:
    """{"ok", "verdict", "feedback", "missing", "review_status"}. ok=False면 재작성."""
    if not validator_4m:
        ok = len(draft) >= 30 and "1)" in draft
        if ok:
            return {"ok": True, "verdict": "합격", "feedback": None, "missing": [],
                    "issues": [], "review_status": DONE}
        if attempts >= MAX_ATTEMPTS:   # 실모델 무한 재작성 방지 — Base 동작 그대로
            return {"ok": True, "verdict": "합격(최대 시도 도달 — 통과 처리)",
                    "feedback": None, "missing": [], "issues": [], "review_status": DONE}
        return {"ok": False, "verdict": "불합격", "missing": [], "issues": [],
                "review_status": None,
                "feedback": (f"응답이 너무 짧습니다({len(draft)}자, 최소 30자). 검토 결과를 "
                             "1) 2) 3) 번호로 구체적으로 작성하세요.")}

    missing = [i["id"] for i in checklist if f"[{i['id']}]" not in draft]
    issues = citation_issues(draft, checklist, documents or [])
    if not missing and not issues:
        status = NEEDS_CHECK if warnings else DONE
        return {"ok": True, "verdict": "합격", "feedback": None, "missing": [], "issues": [],
                "review_status": status}
    if attempts >= MAX_ATTEMPTS:
        return {"ok": True, "verdict": "문제 남음 — 추가 확인 필요", "feedback": None,
                "missing": missing, "issues": issues, "review_status": NEEDS_CHECK}
    problems = []
    if missing:
        problems.append("다음 검증 항목이 보고서에 빠졌습니다. 각 항목을 [ID] 형태로 근거와 함께 "
                        f"모두 포함하세요: {', '.join(missing)}")
    if issues:
        problems.append("근거 인용이 실제 자료와 맞지 않습니다. 목록에 적힌 근거만 그대로 옮기세요: "
                        + " / ".join(issues))
    return {"ok": False, "verdict": "불합격", "missing": missing, "issues": issues,
            "review_status": None, "feedback": "\n".join(problems)}


ITEM_REF = re.compile(rf"\[({ITEM_ID_PATTERN})\]")
DOC_REF = re.compile(r"(QS-[A-Z]{2}-\d{3})(?:\s*Rev\.?\s*([A-Z]))?(?:\s*조항\s*([0-9][0-9.]*))?")


def citation_issues(draft: str, checklist: list[dict], documents: list[dict]) -> list[str]:
    """보고서의 항목·문서·조항·개정판 인용을 실제 데이터와 대조한다."""
    issues = []
    allowed_ids = {i["id"] for i in checklist}
    for item_id in dict.fromkeys(ITEM_REF.findall(draft)):
        if item_id not in allowed_ids:
            issues.append(f"체크리스트에 없는 항목 [{item_id}] 인용")
    read = {d["doc_id"] for d in documents if d.get("found")}
    index = standards_index()
    for doc_id, rev, clause in dict.fromkeys(DOC_REF.findall(draft)):
        if doc_id not in index:
            issues.append(f"존재하지 않는 문서 {doc_id} 인용")
            continue
        if doc_id not in read:
            issues.append(f"조사하지 않은 문서 {doc_id} 인용")
        if rev and rev != index[doc_id]["rev"]:
            issues.append(f"{doc_id} 개정판 오기(Rev.{rev} → 실제 Rev.{index[doc_id]['rev']})")
        clause = clause.rstrip(".")
        if clause and clause not in index[doc_id]["clauses"]:
            issues.append(f"{doc_id}에 없는 조항 {clause} 인용")
    return issues
