"""부하 테스트 — 동시 스트리밍 검토 N건을 보내 처리량, 지연, 대기열 동작을 잰다.

떠 있는 서버(기본 http://127.0.0.1:8100)에 POST /api/v1/reviews/stream을 동시에 보낸다.
서버의 MAX_CONCURRENT_REVIEWS를 넘는 요청은 Queued 이벤트를 받고 기다려야 하며,
모든 요청이 ReviewSaved로 끝나야 한다 (오류·누락 0건).

    LLM_BACKEND=fake MAX_CONCURRENT_REVIEWS=4 python3 server.py   # 다른 터미널
    python3 eval/load_test.py --requests 40 --concurrency 20

측정값:
- 첫 이벤트까지 시간(TTFE) : 요청을 보낸 뒤 처음 화면에 무언가 보이기까지
- 전체 지연              : 저장(ReviewSaved)까지
- 대기열에 걸린 요청 수와 최대 대기 순번
"""
import argparse
import asyncio
import json
import statistics
import time

import httpx

REQUESTS = [
    "차체 대시 패널 라인 용접 로봇(BD-RB-301, BD-RB-302)의 용접 전류 조건을 변경합니다.",
    "프레스 공장 강판 공급사를 A사에서 B사로 변경합니다.",
    "도장 공장 클리어 코트 도막 두께 사양을 변경합니다.",
    "신입 작업자 2명을 의장 공장 도어 트림 공정 야간조에 투입합니다.",
]


async def one(client: httpx.AsyncClient, i: int) -> dict:
    started = time.perf_counter()
    result = {"i": i, "ttfe": None, "latency": None, "queued": None, "saved": False, "error": None}
    try:
        async with client.stream("POST", "/api/v1/reviews/stream",
                                 json={"message": REQUESTS[i % len(REQUESTS)]}) as res:
            res.raise_for_status()
            async for line in res.aiter_lines():
                if not line.startswith("data: "):
                    continue
                if result["ttfe"] is None:
                    result["ttfe"] = time.perf_counter() - started
                data = line[6:]
                if data == "[DONE]":
                    break
                event = json.loads(data)
                if event["type"] == "Queued":
                    result["queued"] = event["position"]
                elif event["type"] == "ReviewSaved":
                    result["saved"] = True
                elif event["type"] == "Error":
                    result["error"] = event.get("message")
    except Exception as exc:   # 연결 거부·시간 초과도 결과에 남긴다
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["latency"] = time.perf_counter() - started
    return result


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1)))]


async def main(base_url: str, total: int, concurrency: int, timeout: float) -> int:
    limiter = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
        health = (await client.get("/api/v1/health")).json()

        async def limited(i: int) -> dict:
            async with limiter:
                return await one(client, i)

        started = time.perf_counter()
        results = await asyncio.gather(*[limited(i) for i in range(total)])
        wall = time.perf_counter() - started

    ok = [r for r in results if r["saved"] and not r["error"]]
    failed = [r for r in results if r not in ok]
    queued = [r["queued"] for r in results if r["queued"]]
    lat = [r["latency"] for r in ok]
    ttfe = [r["ttfe"] for r in ok if r["ttfe"] is not None]
    print(f"서버: {base_url} · LLM {health.get('llm_backend', '?')} · 요청 {total}건 · 동시 {concurrency}")
    print(f"성공 {len(ok)} / 실패 {len(failed)} · 총 {wall:.1f}초 · 처리량 {len(ok) / wall:.2f}건/초")
    if lat:
        print(f"전체 지연  p50 {pct(lat, 50):.2f}s · p95 {pct(lat, 95):.2f}s · 최대 {max(lat):.2f}s")
        print(f"첫 이벤트  p50 {pct(ttfe, 50):.3f}s · p95 {pct(ttfe, 95):.3f}s · 평균 {statistics.mean(ttfe):.3f}s")
    print(f"대기열     {len(queued)}건이 Queued를 받음" + (f" · 최대 순번 {max(queued)}" if queued else ""))
    for r in failed[:5]:
        print(f"  실패 #{r['i']}: {r['error'] or '저장 이벤트 없음'}")
    return 0 if not failed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:8100")
    parser.add_argument("--requests", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.url, args.requests, args.concurrency, args.timeout)))
