"""4M 변경 영향 검토 — MCP Server (Wave 2 축).

Tool / Resource / Prompt 3대 capability를 모두 노출하는 실제 fastmcp 서버.
FastAPI 백엔드가 lifespan에서 이 파일을 subprocess(stdio)로 1회 기동해 프로세스가 살아 있는
동안 재사용한다 (Wave 1 싱글턴 + Wave 2 표준화의 결합).

- Tool     get_equipment_status   : 설비 상태 — 시점마다 달라지는 동적 조회 → Tool
- Tool     get_production_status  : 라인 가동 상태 — 동적 조회 → Tool
- Resource std://shop-standard/{shop}        : 공장별 공정 표준 (common = 4M 공통 규정)
- Resource std://inspection-criteria/{shop}  : 공장별 검사 기준
- Resource rule://required-items, rule://process-flow : 규칙표, 공정 흐름 (정적 문서)
- Prompt   4m_review              : 4M 검토 표준 절차를 강제

오류 규약 — 호출한 Agent가 상황을 구분해 대응할 수 있게 세 가지를 나눈다.
- 입력 형식 위반 (예: 'bad id')       → 입력 스키마 검증 실패 (is_error)
- 형식은 맞지만 대상이 없음           → 정상 응답, found=false
- 데이터 소스를 읽을 수 없음          → ToolError / ResourceError (is_error, 원인 메시지)
- 예상하지 못한 내부 오류             → mask_error_details로 상세를 숨긴다 (서버 로그에만 남음)

데이터는 data/4m/ 아래 교육용 가상 데이터다 (data/4m/README.md 참고).
"""
import json
import re
from pathlib import Path
from typing import Annotated, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import PromptError, ResourceError, ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

SERVER_VERSION = "1.1.0"

mcp = FastMCP(
    name="capstone-4m-ops",
    version=SERVER_VERSION,
    instructions=("완성차 공장(프레스·차체·도장·의장)의 4M 변경 검토용 서버. 설비·라인 상태는 "
                  "Tool로, 표준서·검사 기준·규칙표는 Resource로, 검토 절차는 Prompt로 제공한다. "
                  "모든 데이터는 교육용 가상 데이터다."),
    mask_error_details=True,
)

DATA_DIR = Path(__file__).parent / "data" / "4m"
SHOP_SLUGS = {"프레스": "press", "차체": "body", "도장": "paint", "의장": "assembly",
              "공통": "common"}
PROMPT_SHOPS = set(SHOP_SLUGS)

# 설비 ID(BD-RB-301)와 라인 ID(BD-FLOOR, AS-1) 공통 형식
ID_PATTERN = r"^[A-Z]{2}-[A-Z0-9]+(?:-[A-Z0-9]+)*$"
READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


# ── 출력 스키마 ───────────────────────────────────────────────────────────

class Equipment(BaseModel):
    id: str
    shop: str
    line: str
    name: str
    status: str = Field(description="설비 상태 (예: 정상, 팁 교체 주기 초과, 교정 기한 만료)")
    abnormal: bool = Field(description="정비·교정이 필요한 이상 상태인지")
    note: str = ""


class EquipmentStatus(BaseModel):
    target: str = Field(description="조회한 설비 ID 또는 라인 ID")
    snapshot: str = Field(description="데이터 기준 시각 (ISO 8601)")
    found: bool = Field(description="해당하는 설비가 하나라도 있는지")
    equipment: list[Equipment]


class ProductionStatus(BaseModel):
    line: str
    snapshot: str
    found: bool
    shop: str | None = None
    status: Literal["running", "planned_stop", "unknown"]
    note: str = ""
    models: list[str] = Field(default_factory=list, description="생산 중인 차종")
    wip_bodies: int | None = Field(default=None, description="라인 안의 재공 차체 수")
    body_no_range: str | None = Field(default=None, description="재공 차체 번호 범위")


# ── 데이터 접근 ──────────────────────────────────────────────────────────

def _read_json(name: str) -> dict:
    """데이터 파일을 읽는다. 읽을 수 없으면 원인을 알리는 ToolError — 데이터 소스 장애."""
    try:
        return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolError(f"데이터 소스를 읽을 수 없습니다: {name} ({type(exc).__name__})") from exc


def _index_standards() -> dict[tuple[str, str], Path]:
    """(shop slug, doc_type) → 파일 경로. front-matter를 읽어 만든다."""
    index = {}
    for path in sorted((DATA_DIR / "standards").glob("*.md")):
        m = re.match(r"^---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.S)
        if not m:
            continue
        front = dict(line.split(": ", 1) for line in m.group(1).splitlines() if ": " in line)
        slug = SHOP_SLUGS.get(front.get("shop", ""))
        doc_type = "shop-standard" if front.get("doc_type") == "common-rule" \
            else front.get("doc_type")
        if slug:
            index[(slug, doc_type)] = path
    return index


def _read_standard(shop: str, doc_type: str) -> str:
    valid = sorted({slug for slug, kind in _index_standards() if kind == doc_type})
    if shop not in valid:
        raise ResourceError(f"알 수 없는 공장 '{shop}' — 가능한 값: {', '.join(valid)}")
    try:
        return _index_standards()[(shop, doc_type)].read_text(encoding="utf-8")
    except OSError as exc:
        raise ResourceError(f"문서를 읽을 수 없습니다: {doc_type}/{shop}") from exc


# ── Tools ───────────────────────────────────────────────────────────────

@mcp.tool(annotations=READ_ONLY)
def get_equipment_status(
    target: Annotated[str, Field(pattern=ID_PATTERN, max_length=32,
                                 description="설비 ID(예: BD-RB-301) 또는 라인 ID(예: BD-DASH)")],
) -> EquipmentStatus:
    """설비 ID 또는 라인 ID로 설비 상태를 조회합니다. 라인 ID를 주면 그 라인의 설비 전체를
    돌려줍니다. 해당 설비가 없으면 found=false입니다."""
    data = _read_json("equipment.json")
    equipment = data.get("equipment", {})
    if target in equipment:
        matched = {target: equipment[target]}
    else:
        matched = {k: v for k, v in equipment.items() if v.get("line") == target}
    return EquipmentStatus(
        target=target, snapshot=data.get("snapshot", ""), found=bool(matched),
        equipment=[Equipment(id=k, **v) for k, v in matched.items()])


@mcp.tool(annotations=READ_ONLY)
def get_production_status(
    line: Annotated[str, Field(pattern=ID_PATTERN, max_length=32,
                               description="라인 ID (예: BD-FLOOR)")],
) -> ProductionStatus:
    """라인 ID로 현재 가동 상태를 조회합니다 (running / planned_stop). 없는 라인이면
    found=false, status=unknown입니다."""
    data = _read_json("production.json")
    info = data.get("lines", {}).get(line)
    if info is None:
        return ProductionStatus(line=line, snapshot=data.get("snapshot", ""), found=False,
                                status="unknown", note=f"등록되지 않은 라인: {line}")
    return ProductionStatus(line=line, snapshot=data.get("snapshot", ""), found=True, **info)


# ── Resources ───────────────────────────────────────────────────────────

@mcp.resource("std://shop-standard/{shop}", mime_type="text/markdown")
def get_shop_standard(shop: str) -> str:
    """공장별 공정 표준 (shop: press/body/paint/assembly, common = 4M 변경관리 공통 규정)."""
    return _read_standard(shop, "shop-standard")


@mcp.resource("std://inspection-criteria/{shop}", mime_type="text/markdown")
def get_inspection_criteria(shop: str) -> str:
    """공장별 검사 기준 (shop: press/body/paint/assembly)."""
    return _read_standard(shop, "inspection-criteria")


@mcp.resource("rule://required-items", mime_type="application/json")
def get_required_items() -> str:
    """변경 유형별 공통 필수 검증 항목 규칙표 (JSON)."""
    try:
        return (DATA_DIR / "rules" / "required_items.json").read_text(encoding="utf-8")
    except OSError as exc:
        raise ResourceError("규칙표를 읽을 수 없습니다") from exc


@mcp.resource("rule://process-flow", mime_type="application/json")
def get_process_flow() -> str:
    """공장 간 흐름과 공정 간 영향 규칙 (JSON)."""
    try:
        return (DATA_DIR / "process_flow.json").read_text(encoding="utf-8")
    except OSError as exc:
        raise ResourceError("공정 흐름 규칙을 읽을 수 없습니다") from exc


# ── Prompt ──────────────────────────────────────────────────────────────

@mcp.prompt(name="4m_review")
def four_m_review_prompt(shop: str, request: str) -> str:
    """4M 변경 검토 표준 절차 — planning 노드가 계획을 세울 때 이 절차를 따른다."""
    if shop not in PROMPT_SHOPS:
        raise PromptError(f"알 수 없는 공장 '{shop}' — 가능한 값: {', '.join(sorted(PROMPT_SHOPS))}")
    if not request.strip() or len(request) > 2000:
        raise PromptError("요청 내용은 1~2000자여야 합니다")
    return f"""다음 4M 변경 요청에 대해 표준 검토 절차를 수행하세요.

## 변경 요청
- 공장: {shop}
- 요청 내용: {request}

## 검토 절차 (반드시 순서대로 수행)
1. 4M 공통 규정(std://shop-standard/common)에서 변경 등급과 초기유동관리 기준을 확인하세요.
2. 해당 공장의 공정 표준(std://shop-standard/...)과 검사 기준(std://inspection-criteria/...)을 확인하세요.
3. 요청에 등장한 설비와 라인의 상태를 get_equipment_status, get_production_status Tool로 확인하세요.
4. 변경이 다음 공장(프레스 → 차체 → 도장 → 의장)에 주는 영향이 있는지 확인하세요.
5. 검증 항목마다 [ID]와 근거(문서ID, 개정판, 조항)를 표기하세요.
"""


if __name__ == "__main__":
    try:
        mcp.run(show_banner=False)
    except TypeError:   # 구버전 fastmcp 호환
        mcp.run()
