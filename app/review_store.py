"""검토 이력 저장소 — 검토 결과, 사용자 피드백, 평가 결과를 SQLite에 남긴다.

세션 저장소(agent/session_store.py)와 같은 DB 파일을 쓰되 테이블을 분리한다. 서버가
재시작돼도 이력이 유지된다(Wave 12와 같은 이유).
"""
from __future__ import annotations   # 메서드 이름 list가 타입 표기 list[dict]를 가리지 않게

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


class SqliteReviewStore:
    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS reviews ("
            " id TEXT PRIMARY KEY, thread_id TEXT, request TEXT, body TEXT, created TEXT)"
        )
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS feedback ("
            " id TEXT PRIMARY KEY, review_id TEXT, score INTEGER, comment TEXT,"
            " langsmith_feedback_id TEXT, created TEXT)"
        )
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS evaluations (id TEXT PRIMARY KEY, body TEXT, created TEXT)"
        )
        self.conn.commit()

    def save(self, thread_id: str, request: str, body: dict) -> dict:
        """body(검토 결과)에 id와 created_at을 붙여 저장하고 그대로 돌려준다."""
        review = {"id": f"rv-{uuid.uuid4().hex[:12]}",
                  "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "thread_id": thread_id, "request": request, **body}
        self.conn.execute(
            "INSERT INTO reviews VALUES (?,?,?,?,?)",
            (review["id"], thread_id, request, json.dumps(review, ensure_ascii=False),
             review["created_at"]),
        )
        self.conn.commit()
        return review

    def get(self, review_id: str) -> dict | None:
        row = self.conn.execute("SELECT body FROM reviews WHERE id=?", (review_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, limit: int = 20, offset: int = 0) -> tuple[list[dict], int]:
        rows = self.conn.execute(
            "SELECT body FROM reviews ORDER BY created DESC, rowid DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        total = self.conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        return [json.loads(r[0]) for r in rows], total

    # ── 피드백 ─────────────────────────────────────────────────────────
    def add_feedback(self, review_id: str, score: int, comment: str | None,
                     langsmith_feedback_id: str | None) -> dict:
        fb = {"id": f"fb-{uuid.uuid4().hex[:12]}", "review_id": review_id, "score": score,
              "comment": comment, "langsmith_feedback_id": langsmith_feedback_id,
              "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.conn.execute("INSERT INTO feedback VALUES (?,?,?,?,?,?)",
                          (fb["id"], review_id, score, comment, langsmith_feedback_id,
                           fb["created_at"]))
        self.conn.commit()
        return fb

    def list_feedback(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT f.id, f.review_id, f.score, f.comment, f.langsmith_feedback_id, f.created,"
            " r.request FROM feedback f LEFT JOIN reviews r ON r.id = f.review_id"
            " ORDER BY f.created DESC, f.rowid DESC LIMIT ?", (limit,)).fetchall()
        keys = ["id", "review_id", "score", "comment", "langsmith_feedback_id", "created_at",
                "request"]
        return [dict(zip(keys, row)) for row in rows]

    def feedback_for(self, review_id: str) -> list[dict]:
        return [f for f in self.list_feedback(limit=1000) if f["review_id"] == review_id]

    # ── 평가 결과 ───────────────────────────────────────────────────────
    def save_evaluation(self, job: dict) -> None:
        self.conn.execute("INSERT OR REPLACE INTO evaluations VALUES (?,?,?)",
                          (job["id"], json.dumps(job, ensure_ascii=False), job["created_at"]))
        self.conn.commit()

    def list_evaluations(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute("SELECT body FROM evaluations ORDER BY created DESC LIMIT ?",
                                 (limit,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def get_evaluation(self, job_id: str) -> dict | None:
        row = self.conn.execute("SELECT body FROM evaluations WHERE id=?", (job_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def close(self) -> None:
        self.conn.close()
