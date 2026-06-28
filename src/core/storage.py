import sqlite3
import json
import os
from dataclasses import asdict
from typing import List, Optional
from src.core.models import BuilderInput, TaskResult, CallChainEntry


class Storage:
    """日志持久化 — SQLite 存储对话消息 + 任务日志"""

    def __init__(self, db_path: str = "data/agent.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_tables()

    def _get_conn(self):
        """获取数据库连接，WAL 模式，提升并发"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_tables(self):
        """建表：对话消息 + 任务日志"""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL UNIQUE,
                    session_id TEXT DEFAULT 'default',
                    task_status TEXT NOT NULL,
                    frontend_json TEXT,
                    log_json TEXT,
                    results_json TEXT,
                    call_chain_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # 兼容旧表：无 results_json / call_chain_json 列时自动补齐
            for col in ("results_json", "call_chain_json"):
                try:
                    conn.execute(f"ALTER TABLE task_logs ADD COLUMN {col} TEXT")
                except sqlite3.OperationalError:
                    pass  # 列已存在
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_logs_session ON task_logs(session_id)")

    def save_message(self, session_id: str, role: str, content: str) -> None:
        """保存单条对话消息"""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content),
            )

    def get_messages(self, session_id: str, limit: int = 20) -> List[dict]:
        """获取会话消息"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY created_at ASC LIMIT ?",
                (session_id, limit),
            ).fetchall()
            return [{"role": row["role"], "content": row["content"]} for row in rows]

    def save_task_log(
        self, task_id: str, session_id: str,
        frontend: dict, log: dict,
        results: Optional[List[TaskResult]] = None,
        call_chain: Optional[List[CallChainEntry]] = None,
    ) -> None:
        """保存任务日志（含结果和调用链，便于重建 BuilderInput）"""
        # 将 dataclass 对象列表转为可 JSON 序列化的字典列表
        results_dicts = [asdict(r) for r in results] if results else []
        chain_dicts = [asdict(c) for c in call_chain] if call_chain else []
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO task_logs "
                    "(task_id, session_id, task_status, frontend_json, log_json, results_json, call_chain_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        task_id,
                        session_id,
                        log.get("task_status", "UNKNOWN"),
                        json.dumps(frontend, ensure_ascii=False),
                        json.dumps(log, ensure_ascii=False),
                        json.dumps(results_dicts, ensure_ascii=False),
                        json.dumps(chain_dicts, ensure_ascii=False),
                    ),
                )
        except Exception:
            pass  # 写入失败不阻断主流程

    def list_sessions(self) -> List[str]:
        """列出所有已知的 session_id,按最新消息降序"""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT session_id, MAX(created_at) AS last_ts FROM (
                    SELECT session_id, created_at FROM messages
                    UNION ALL
                    SELECT session_id, created_at FROM task_logs
                ) GROUP BY session_id ORDER BY last_ts DESC
            """).fetchall()
            return [row["session_id"] for row in rows]

    def get_first_message(self, session_id: str) -> str:
        """取某个会话最早的用户消息，用作会话标签"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT content FROM messages WHERE session_id = ? AND role = 'user' "
                "ORDER BY created_at ASC LIMIT 1",
                (session_id,),
            ).fetchone()
            return row["content"] if row else "新对话"

    def get_last_task_input(self, session_id: str) -> Optional[BuilderInput]:
        """取某个会话最后一次任务的 BuilderInput（仅限新列完整的数据）"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT task_id, task_status, results_json, call_chain_json "
                "FROM task_logs WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
                (session_id,)
            ).fetchone()
            if not row:
                return None

            results_raw = row["results_json"]
            chain_raw = row["call_chain_json"]

            # 升级前的旧日志没有这两列，无法可靠恢复，直接跳过
            if not results_raw or not chain_raw:
                return None

            return BuilderInput(
                task_id=row["task_id"],
                final_status=row["task_status"],
                results=[TaskResult(**r) for r in json.loads(results_raw)],
                call_chain=[CallChainEntry(**c) for c in json.loads(chain_raw)],
            )
