"""SQLite 저장소 — 작업 스레드에서 동시에 불러도 안전한가 (asyncio.to_thread로 부르는 전제)."""
import asyncio

from agent.session_store import SqliteSessionStore
from app.review_store import SqliteReviewStore


def test_review_store_concurrent_writes(tmp_path):
    store = SqliteReviewStore(tmp_path / "t.db")

    async def main():
        await asyncio.gather(*[
            asyncio.to_thread(store.save, f"th-{i}", f"요청 {i}", {"review_status": "검토 완료"})
            for i in range(50)])
        return await asyncio.to_thread(store.list, 100, 0)

    items, total = asyncio.run(main())
    assert total == 50 and len({r["id"] for r in items}) == 50
    store.close()


def test_session_store_concurrent_appends_keep_threads_separate(tmp_path):
    store = SqliteSessionStore(tmp_path / "s.db")

    async def main():
        await asyncio.gather(*[
            asyncio.to_thread(store.append, f"th-{i % 5}", "user", f"m{i}") for i in range(100)])
        return [await asyncio.to_thread(store.load, f"th-{k}") for k in range(5)]

    histories = asyncio.run(main())
    assert [len(h) for h in histories] == [20] * 5
    store.close()
