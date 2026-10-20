"""조사 Agent 2종 — Supervisor가 LangGraph에서 병렬로 실행한다 (Wave 10b).

- Standards Agent  : 표준서·검사 기준을 MCP Resource로 읽는다(키워드 방식), 또는 공통 규정만
                     전체를 읽고 공장 조항은 MCP Tool search_standards로 의미 검색한다(RAG 방식)
- Field Data Agent : 설비·라인 상태를 MCP Tool로 조회하고(Wave 9 재시도), 현장 데이터
                     항목(③ EXT-EQ-01, EXT-LOT-01)을 코드 규칙으로 판정한다

URI나 서버를 하드코딩하지 않고, resource는 이름으로 연결된 서버들을 조회
(find_resource_template)해 찾은 뒤에만 요청한다 (Wave 2).

장애 격리: 문서 하나, 설비 하나의 조회가 실패해도(MCP 오류, 시간 초과, 데이터 소스 장애)
검토 전체를 멈추지 않는다. 그 항목만 실패로 기록하고 경고를 남겨 최종 상태를
"추가 확인 필요"로 만든다 — 조회 못 한 것을 조회한 척하지 않는다.
"""
import asyncio

import logging
import re

from ..domain_4m import FIELD_ITEMS, SHOP_SLUGS, lines_of, parse_doc
from ..mcp_client import MCP_REQUEST_ERRORS
from ..retry import with_retry

logger = logging.getLogger("agent")

RESOURCE_NAMES = {"standard": "get_shop_standard", "inspection": "get_inspection_criteria"}
TOOL_NAMES = {"equipment": ("get_equipment_status", "target"),
              "production": ("get_production_status", "line")}


async def fetch_documents(mcp, tasks: list[dict]) -> tuple[list[dict], list[dict]]:
    """(documents, 실행 결과 events). 문서를 못 찾은 task는 found=False로 남긴다."""
    templates = {}
    for kind in {t["kind"] for t in tasks}:
        templates[kind] = await mcp.find_resource_template(RESOURCE_NAMES[kind])

    async def read(task: dict) -> dict:
        server, uri_template = templates[task["kind"]]
        uri = uri_template.format(shop=SHOP_SLUGS.get(task["target"], "common"))
        doc = {"task_id": task["id"], "doc_type": task["kind"], "target": task["target"],
               "found": False, "doc_id": None, "rev": None, "title": None, "clauses": [],
               "error": None}
        try:
            front, clauses = parse_doc(await mcp.read_resource(uri, server=server))
        except MCP_REQUEST_ERRORS as exc:
            logger.warning("resource read failed %s: %s", uri, exc)
            doc["error"] = f"{type(exc).__name__}: {exc}"[:200]
            return doc
        doc.update(found=bool(clauses), doc_id=front.get("doc_id"), rev=front.get("rev"),
                   title=front.get("title"),
                   clauses=[{"no": no, "title": title, "text": text}
                            for no, title, text in clauses])
        return doc

    documents = await asyncio.gather(*(read(t) for t in tasks))
    events = [{"type": "TaskCompleted", "id": d["task_id"], "source": d["doc_type"],
               "target": d["target"], "retries": 0, "found": d["found"],
               "failed": d["error"] is not None,
               "doc_id": d["doc_id"], "rev": d["rev"], "title": d["title"]} for d in documents]
    return list(documents), events


RAG_TOP_K = 4   # 평가 10건에서 근거 조항 8/8을 찾은 최소 k (bge-m3, fake 모두)


async def search_documents(mcp, query: str, classification: dict,
                           k: int = RAG_TOP_K) -> tuple[list[dict], list[dict], str | None]:
    """공장 조항을 RAG로 검색해 문서 단위로 묶는다. (documents, events, 실패 경고).

    검색 결과는 fetch_documents와 같은 문서 형식으로 돌려준다 — 조항이 일부만 들어 있을 뿐
    이후 판정·근거 인용 단계는 키워드 방식과 똑같이 동작한다."""
    args = {"query": query, "k": k, "change_types": classification.get("change_types", [])}
    if classification.get("shop"):
        args["shop"] = classification["shop"]
    try:
        result, retries = await with_retry(mcp.call_tool, "search_standards", args)
    except MCP_REQUEST_ERRORS as exc:
        logger.warning("standards search failed: %s", exc)
        return [], [{"type": "RetrievalCompleted", "hits": [], "k": k, "failed": True}], \
            "표준서 검색을 수행하지 못했습니다."
    by_doc: dict[str, dict] = {}
    for hit in result["hits"]:
        doc = by_doc.setdefault(hit["doc_id"], {
            "task_id": f"rag-{hit['doc_id']}", "doc_type": hit["doc_type"],
            "target": hit["shop"], "found": True, "doc_id": hit["doc_id"], "rev": hit["rev"],
            "title": hit["title"], "clauses": [], "error": None, "retrieved": True})
        doc["clauses"].append({"no": hit["clause"], "title": hit["clause_title"],
                               "text": hit["text"], "score": hit["score"]})
    for doc in by_doc.values():
        doc["clauses"].sort(key=lambda c: [int(x) if x.isdigit() else x
                                           for x in re.split(r"(\d+)", c["no"])])
    event = {"type": "RetrievalCompleted", "k": k, "retries": retries,
             "embedding": result.get("embedding"), "chunk_count": result.get("chunk_count"),
             "hits": [f"{h['doc_id']} 조항 {h['clause']}" for h in result["hits"]],
             "top_score": result["hits"][0]["score"] if result["hits"] else None}
    return list(by_doc.values()), [event], None


async def fetch_field_data(mcp, tasks: list[dict]) -> tuple[list[dict], int, list[dict],
                                                           list[str]]:
    """(findings, 재시도 합계, events, 조회 실패 경고)."""
    async def call(task: dict) -> tuple[dict, list[dict], int, str | None]:
        name, arg = TOOL_NAMES[task["kind"]]
        try:
            data, retries = await with_retry(mcp.call_tool, name, {arg: task["target"]})
        except MCP_REQUEST_ERRORS as exc:
            logger.warning("tool call failed %s(%s): %s", name, task["target"], exc)
            failed = {"kind": task["kind"], "target": task["target"], "name": "",
                      "line": None, "status": "조회 실패", "abnormal": False,
                      "note": f"{type(exc).__name__}", "failed": True}
            return task, [failed], 0, f"{KIND_KO[task['kind']]} {task['target']} 상태를 조회하지 못했습니다."
        if task["kind"] == "equipment":
            found = [{"kind": "equipment", "target": eq["id"], "name": eq.get("name", ""),
                      "line": eq.get("line"), "status": eq.get("status", ""),
                      "abnormal": bool(eq.get("abnormal")), "note": eq.get("note", "")}
                     for eq in data.get("equipment", [])]
        else:
            found = [{"kind": "production", "target": data.get("line", task["target"]),
                      "name": "", "line": data.get("line"), "status": data.get("status"),
                      "abnormal": data.get("status") == "running",
                      "note": data.get("note", "")}]
        return task, found, retries, None

    results = await asyncio.gather(*(call(t) for t in tasks))
    findings, seen, retry_total, events, warnings = [], set(), 0, [], []
    for task, found, retries, warning in results:
        retry_total += retries
        if warning:
            warnings.append(warning)
        for f in found:
            key = (f["kind"], f["target"])
            if key not in seen:
                seen.add(key)
                findings.append(f)
        events.append({"type": "TaskCompleted", "id": task["id"], "source": task["kind"],
                       "target": task["target"], "retries": retries, "failed": bool(warning),
                       "summary": warning or _summary(task, found)})
    return findings, retry_total, events, warnings


LINE_STATUS = {"running": "가동 중", "planned_stop": "계획정지", "unknown": "확인 불가"}
KIND_KO = {"equipment": "설비", "production": "라인"}


def _summary(task: dict, found: list[dict]) -> str:
    """활동 로그용 한 줄 요약 — 무엇을 조회해 어떤 상태였는지."""
    if task["kind"] == "production":
        f = found[0]
        return f"라인 {f['target']}: {LINE_STATUS.get(f['status'], f['status'])} ({f['note']})"
    if not found:
        return f"설비 {task['target']}: 조회 결과 없음"
    states = ", ".join(f"{f['target']} {f['status']}" for f in found)
    return f"설비 상태 ({task['target']}): {states}"


def field_items(findings: list[dict], classification: dict,
                documents: list[dict]) -> list[dict]:
    """현장 데이터 항목(③) — QS-CM-001 조항 4, 5를 코드 규칙으로 적용한다.

    - EXT-EQ-01: 요청에 명시된 설비가 이상 상태이고, 이번 변경으로 교체되지 않을 때
                 (Machine 변경이면 명시된 설비는 교체·철거 대상이므로 제외)
    - EXT-LOT-01: 변경 대상 라인(명시 라인 + 명시 설비의 라인)이 가동 중일 때
    같은 라인에 있어도 요청에 명시되지 않은 설비의 이상은 정보로만 남긴다."""
    mentioned = set(classification.get("equipment_ids", []))
    replaced = "Machine" in classification.get("change_types", [])
    target_lines = set(lines_of(list(mentioned), classification.get("lines", [])))
    clause_of = _clause_index(documents)

    items = []
    abnormal = [f["target"] for f in findings if f["kind"] == "equipment"
                and f["abnormal"] and f["target"] in mentioned]
    if abnormal and not replaced:
        items.append(_field_item("EXT-EQ-01", clause_of, "equipment", abnormal))
    running = [f["target"] for f in findings if f["kind"] == "production"
               and f["status"] == "running" and f["target"] in target_lines]
    if running:
        items.append(_field_item("EXT-LOT-01", clause_of, "production", running))
    return items


def _clause_index(documents: list[dict]) -> dict[str, dict]:
    """항목 ID → 그 ID가 적힌 첫 조항 (문서ID, 개정판, 조항 번호, 제목)."""
    index = {}
    for d in documents:
        for c in d.get("clauses", []):
            for item_id in FIELD_ITEMS:
                if f"({item_id})" in c["text"] and item_id not in index:
                    index[item_id] = {"doc_id": d["doc_id"], "rev": d["rev"],
                                      "clause": c["no"], "clause_title": c["title"]}
    return index


def _field_item(item_id: str, clause_of: dict, tool: str, targets: list[str]) -> dict:
    evidence = {**clause_of.get(item_id, {}), "tool": tool, "targets": targets}
    return {"id": item_id, "name": FIELD_ITEMS[item_id], "layer": "field",
            "evidence": evidence}
