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


def test_unfinished_evaluations_marked_interrupted_on_restart(tmp_path):
    """평가 도중 서버가 죽으면 다음 기동 때 그 작업은 interrupted가 된다 (새 평가를 막지 않게)."""
    from app.evaluation import INTERRUPTED_MESSAGE, EvaluationManager

    db = tmp_path / "e.db"
    store = SqliteReviewStore(db)
    base = {"created_at": "2026-10-20T00:00:00+00:00", "profiles": ["improved"], "case_count": 3,
            "llm_backend": "fake", "progress": {"done": 1, "total": 3}, "dataset": "d",
            "experiments": [], "error": None}
    store.save_evaluation({**base, "id": "ev-run", "status": "running"})
    store.save_evaluation({**base, "id": "ev-done", "status": "completed"})
    store.close()

    restarted = SqliteReviewStore(db)            # 새 프로세스
    manager = EvaluationManager(runtime=None, langsmith=None, store=restarted)
    assert manager.get("ev-run")["status"] == "interrupted"
    assert manager.get("ev-run")["error"] == INTERRUPTED_MESSAGE
    assert manager.get("ev-done")["status"] == "completed"
    restarted.close()
