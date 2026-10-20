"""Wave 12 — 프로세스 밖(SQLite 파일)에 두는 세션 저장소.

서버가 재시작돼도(새 프로세스, 새 인스턴스) 같은 session.db 파일을 다시 열므로
대화 이력이 유지된다. in-memory dict였다면 재시작 즉시 소실됐을 상태다.

sqlite3 호출은 동기라 이벤트 루프를 막는다. 비동기 코드에서는 asyncio.to_thread로 작업
스레드에서 부르고, 연결 하나를 여러 스레드가 공유하므로 메서드마다 잠금(@locked)을 건다.
"""
import functools
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "session.db"


def locked(method):
    """self._lock을 잡고 실행한다 — 공유 연결에서 쿼리와 commit이 섞이지 않게."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class SqliteSessionStore:
    def __init__(self, db_path: Path = DB_PATH):
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS messages ("
            " thread_id TEXT, role TEXT, content TEXT, created TEXT)"
        )
        self.conn.commit()

    @locked
    def load(self, thread_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT role, content FROM messages WHERE thread_id=? ORDER BY rowid",
            (thread_id,),
        ).fetchall()
        return [{"role": r, "content": c} for r, c in rows]

    @locked
    def append(self, thread_id: str, role: str, content: str) -> None:
        self.conn.execute(
            "INSERT INTO messages VALUES (?,?,?,?)",
            (thread_id, role, content, datetime.now().isoformat()),
        )
        self.conn.commit()

    @locked
    def close(self) -> None:
        self.conn.close()
