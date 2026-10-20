"""SSE 스트리밍 규약 테스트 — keep-alive, 연결 끊김 시 실행 취소, 순번(seq).

실제 그래프 대신 느리게 이벤트를 내는 가짜 런타임으로 타이밍을 통제한다.
"""
import asyncio
import json

from app.routers import _agent


class SlowRuntime:
    """이벤트 사이에 지연을 두는 가짜 런타임. 취소되면 cancelled를 기록한다."""

    def __init__(self, gap: float, events: int = 2):
        self.gap = gap
        self.events = events
        self.cancelled = False

    async def stream(self, message, thread_id, forced_route=None):
        try:
            for i in range(self.events):
                if i:
                    await asyncio.sleep(self.gap)
                yield {"type": "NodeStarted", "node": "classify"}
            yield {"type": "RunCompleted", "state": {"final": "ok"}}
        except asyncio.CancelledError:
            self.cancelled = True
            raise


async def _collect(gen) -> list[str]:
    return [frame async for frame in gen]


def test_keep_alive_frames_are_sent_while_idle(monkeypatch):
    monkeypatch.setattr(_agent, "HEARTBEAT_SECONDS", 0.05)
    frames = asyncio.run(_collect(_agent.sse_stream(SlowRuntime(gap=0.3), "m", "t", "req")))
    assert ": keep-alive\n\n" in frames
    data = [json.loads(f[6:]) for f in frames if f.startswith("data: {")]
    assert [d["seq"] for d in data] == [1, 2]
    assert frames[-1] == "data: [DONE]\n\n"


def test_client_disconnect_cancels_run_and_skips_save():
    runtime = SlowRuntime(gap=5.0)
    saved = []

    async def on_complete(state, activity, run_id):
        saved.append(state)
        return {"type": "ReviewSaved", "id": "rv-x"}

    async def main():
        gen = _agent.sse_stream(runtime, "m", "t", "req", on_complete=on_complete)
        consumer = asyncio.create_task(gen.__anext__())   # 첫 이벤트까지 받은 뒤
        first = await consumer
        reader = asyncio.create_task(gen.__anext__())     # 다음 이벤트를 기다리는 중에
        await asyncio.sleep(0.05)
        reader.cancel()                                   # 클라이언트가 연결을 끊는다
        try:
            await reader
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0.05)
        return first

    first = asyncio.run(main())
    assert json.loads(first[6:])["type"] == "NodeStarted"
    assert runtime.cancelled is True     # 그래프 실행이 취소됐다
    assert saved == []                   # 미완성 검토는 저장하지 않는다
