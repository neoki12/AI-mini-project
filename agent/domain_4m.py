"""4M 도메인 지식 — data/4m/에서 읽은 공장·설비·라인·규칙표·공정 흐름과 키워드 판별.

장애 대응 버전의 KNOWN_SYSTEMS 역할을 대신한다. 키워드 판별(guess_*)은 두 곳에서 쓴다.
- LLM 출력의 코드 레벨 보정과 LLM 실패 시 fallback (W6 정신: 모델 출력을 그대로 믿지 않는다)
- fake 백엔드의 결정론적 응답 (llm/fake_chat.py)
"""
import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "4m"

SHOPS = ["프레스", "차체", "도장", "의장"]
COMMON = "공통"
# MCP Resource URI에는 영문 slug를 쓴다 (std://shop-standard/{shop})
SHOP_SLUGS = {"프레스": "press", "차체": "body", "도장": "paint", "의장": "assembly",
              COMMON: "common"}
CHANGE_TYPES = ["Man", "Machine", "Material", "Method"]
RESEARCH_KINDS = ["standard", "inspection", "equipment", "production"]

# 현장 데이터(③)로 판단하는 항목 — 문서 조건 판정(judge) 대상이 아니라 코드가 Tool 결과로 정한다
FIELD_ITEMS = {"EXT-EQ-01": "설비 이상 상태에서의 변경 — 정비·교정 선행",
               "EXT-LOT-01": "가동 중 변경 — 변경 전후 차체 구분·추적"}
ITEM_ID_PATTERN = r"(?:COM|MAN|MAC|MAT|MET|EXT|DS)-(?:[A-Z]+-)?\d+"
# QS-AS-001 조항 2 — 안전 체결부로 지정된 계통. 요청에 나오면 안전 항목을 LLM 판정과 무관하게 포함한다
SAFETY_SYSTEMS = ["브레이크", "조향", "에어백", "시트벨트", "연료"]
SAFETY_ITEMS = ["EXT-AS-01", "EXT-AS-02"]
# QS-CM-001 조항 3 — 등급별 초기유동관리 기간
INITIAL_FLOW_PERIOD = {"A": "3개월", "B": "1개월", "C": "2주"}
APPROVER = {"A": "품질본부 승인", "B": "공장 품질팀 승인", "C": "공장 자체 관리"}


def _load(name: str) -> dict:
    try:
        return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


EQUIPMENT: dict[str, dict] = _load("equipment.json").get("equipment", {})
LINES: dict[str, dict] = _load("production.json").get("lines", {})
RULES: dict = _load("rules/required_items.json")
FLOW: dict = _load("process_flow.json")

# 공장명이 직접 나오지 않을 때 쓰는 보조 키워드
SHOP_KEYWORDS = {
    "프레스": ["금형", "강판", "블랭크"],
    "차체": ["용접", "지그", "구조용 접착제"],
    "도장": ["도료", "오븐", "상도", "전착", "실링"],
    "의장": ["조립", "체결", "너트러너", "트림", "시트벨트", "브레이크", "협력사"],
}

MAN_KEYWORDS = ["작업자", "담당자", "신입", "인원"]
MACHINE_NOUNS = ["로봇", "금형", "설비", "지그", "너트러너", "용접건"]
MACHINE_VERBS = ["교체", "도입", "신형", "수정", "이설"]
MATERIAL_KEYWORDS = ["공급사", "강판", "도료", "접착제", "실러", "부품", "협력사", "재질"]
METHOD_KEYWORDS = ["조건", "온도", "프로파일", "토크", "전류", "순서", "파라미터", "공법", "속도"]


def _first_hit(query: str, words) -> int | None:
    positions = [query.index(w) for w in words if w in query]
    return min(positions) if positions else None


def find_equipment_ids(query: str) -> list[str]:
    return [eq for eq in EQUIPMENT if eq in query]


def find_lines(query: str) -> list[str]:
    """쿼리에 직접 나온 라인 + 쿼리에 나온 설비가 속한 라인."""
    lines = [line for line in LINES if line in query]
    for eq in find_equipment_ids(query):
        line = EQUIPMENT[eq].get("line")
        if line and line not in lines:
            lines.append(line)
    return lines


def lines_of(equipment_ids: list[str], lines: list[str]) -> list[str]:
    """명시된 라인 + 명시된 설비가 속한 라인 (중복 제거, 순서 유지)."""
    result = list(lines)
    for eq in equipment_ids:
        line = EQUIPMENT.get(eq, {}).get("line")
        if line and line not in result:
            result.append(line)
    return result


def guess_shop(query: str) -> str | None:
    """공장명 직접 언급 → 설비/라인 ID → 보조 키워드 순으로 찾는다. 못 찾으면 None."""
    explicit = [(query.index(s), s) for s in SHOPS if s in query]
    if explicit:
        return min(explicit)[1]
    for eq in find_equipment_ids(query):
        return EQUIPMENT[eq]["shop"]
    for line in find_lines(query):
        return LINES[line]["shop"]
    hits = [(pos, shop) for shop, words in SHOP_KEYWORDS.items()
            if (pos := _first_hit(query, words)) is not None]
    return min(hits)[1] if hits else None


def guess_change_types(query: str) -> list[str]:
    """키워드 매핑으로 변경 유형을 고른다. 복합 변경이면 여러 개를 돌려준다.

    Machine은 설비 명사와 교체·도입 동사가 함께 있어야 한다 — '로봇의 전류 조건 변경'처럼
    설비가 언급돼도 설비 자체는 그대로인 Method 변경을 Machine으로 오판하지 않기 위함."""
    types = []
    if any(w in query for w in MAN_KEYWORDS):
        types.append("Man")
    if any(n in query for n in MACHINE_NOUNS) and any(v in query for v in MACHINE_VERBS):
        types.append("Machine")
    if any(w in query for w in MATERIAL_KEYWORDS):
        types.append("Material")
    if any(w in query for w in METHOD_KEYWORDS):
        types.append("Method")
    return types or ["Method"]


def valid_target(kind: str, target: str) -> bool:
    if kind == "standard":
        return target in SHOPS or target == COMMON
    if kind == "inspection":
        return target in SHOPS
    if kind == "equipment":
        return target in EQUIPMENT or target in LINES
    if kind == "production":
        return target in LINES
    return False


def required_items(change_types: list[str]) -> list[str]:
    """규칙표(①) — 복합 변경이면 유형별 규칙의 합집합 (정렬)."""
    items: set[str] = set()
    for ct in change_types:
        items.update(RULES.get("rules", {}).get(ct, []))
    return sorted(items)


def item_name(item_id: str) -> str:
    return (RULES.get("items", {}).get(item_id) or FLOW.get("items", {}).get(item_id)
            or FIELD_ITEMS.get(item_id) or item_id)


def flow_candidates(shop: str | None, change_types: list[str]) -> list[dict]:
    """공정 흐름 규칙 중 출발 공장과 변경 유형이 맞는 후보. 주제(subject)가 맞는지는 judge가 본다."""
    return [r for r in FLOW.get("rules", [])
            if r["from_shop"] == shop and r["change_type"] in change_types]


def parse_doc(text: str) -> tuple[dict, list[tuple[str, str, str]]]:
    """표준서 Markdown → (front-matter, [(조항 번호, 제목, 본문)])."""
    front = {}
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if m:
        front = dict(line.split(": ", 1) for line in m.group(1).splitlines() if ": " in line)
    clauses = [(c.group(1), c.group(2).strip(), c.group(3).strip())
               for c in re.finditer(r"^## 조항 (\S+) ([^\n]*)\n(.*?)(?=^## |\Z)",
                                    text, re.S | re.M)]
    return front, clauses
