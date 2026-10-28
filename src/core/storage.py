import sqlite3
import json
import os
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
        """建表：会话元数据 + 对话消息 + 任务日志 + 审计记录"""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions(
                    session_id TEXT PRIMARY KEY,
                    label TEXT DEFAULT '新对话',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
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
                    internal_task_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_audits(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    audit_type TEXT NOT NULL,
                    quality_score REAL,
                    issues TEXT,
                    human_feedback TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (task_id) REFERENCES task_logs(task_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_messages(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    session_id TEXT DEFAULT 'default',
                    from_agent TEXT NOT NULL,
                    to_agent TEXT NOT NULL,
                    step INTEGER DEFAULT 0,
                    message_type TEXT NOT NULL,
                    content TEXT,
                    artifacts TEXT,
                    status TEXT,
                    issues TEXT,
                    role TEXT,
                    reference_step INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_logs_session ON task_logs(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_audits_task ON task_audits(task_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_messages_task ON agent_messages(task_id)")

        # 先补列再建依赖新列的索引：
        # idx_agent_messages_session 依赖 session_id，而该列在早期版本中不存在。
        # 若在建索引之前不补列，老库升级会直接抛 "no such column: session_id"
        # 而无法启动（此前存在的顺序缺陷，随 T-12 加列一并修正）。
        self._check_columns()

        with self._get_conn() as conn:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_messages_session ON agent_messages(session_id)")

    def _check_columns(self):
        """补齐旧表缺失列：先查目录再 ALTER，避免吞掉非预期的数据库错误"""
        with self._get_conn() as conn:
            existing = {
                row["name"] for row in
                conn.execute("PRAGMA table_info(task_logs)").fetchall()
            }
        for col in ("results_json", "call_chain_json", "user_input", "internal_task_id"):
            if col not in existing:
                with self._get_conn() as conn:
                    conn.execute(f"ALTER TABLE task_logs ADD COLUMN {col} TEXT")

        # 回填 internal_task_id：历史库中该字段只藏在 log_json 里。
        # 该映射此前只存在于 Redis（TTL 1 小时），过期后历史任务的 Agent 协作
        # 视图（agent_messages）将永久无法关联——这正是"关掉再打开就看不到"的根因。
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE task_logs SET internal_task_id = "
                "json_extract(log_json, '$.task_id') "
                "WHERE internal_task_id IS NULL "
                "AND json_valid(log_json) "
                "AND json_extract(log_json, '$.task_id') IS NOT NULL"
            )

        # 平滑升级：老库若已存在 agent_messages 但缺列，补齐
        # role（T-13）：执行方 Agent 名，避免前端按 message_type 反推
        # reference_step（T-12）：依赖的上游步骤号，供前端绘制产物依赖连线
        with self._get_conn() as conn:
            am_cols = {
                row["name"] for row in
                conn.execute("PRAGMA table_info(agent_messages)").fetchall()
            }
        for col, coltype in (("session_id", "TEXT"), ("status", "TEXT"),
                             ("issues", "TEXT"), ("role", "TEXT"),
                             ("reference_step", "INTEGER")):
            if am_cols and col not in am_cols:
                with self._get_conn() as conn:
                    conn.execute(f"ALTER TABLE agent_messages ADD COLUMN {col} {coltype}")

        with self._get_conn() as conn:
            session_cols = {
                row["name"] for row in
                conn.execute("PRAGMA table_info(sessions)").fetchall()
            }
        if "updated_at" not in session_cols:
            with self._get_conn() as conn:
                conn.execute("ALTER TABLE sessions ADD COLUMN updated_at TIMESTAMP")

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

    def save_audit(
            self, 
            task_id: str, 
            audit_type: str, 
            quality_score: float, 
            issues: List[str] = None, 
            human_feedback: Optional[dict] = None
        ) -> None:
        """保存审计报告到task_sudits"""
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT INTO task_audits(task_id, audit_type, quality_score, issues, human_feedback)"
                    "VALUES(?, ?, ?, ?, ?)",
                    (
                        task_id,
                        audit_type,
                        quality_score,
                        json.dumps(issues, ensure_ascii=False) if issues else None,
                        json.dumps(human_feedback, ensure_ascii=False) if human_feedback else None,
                    ),
                )
        except Exception:
            pass    #静默跳过

    def get_audits(self, task_id: str) -> List[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM task_audits WHERE task_id = ? ORDER BY created_at ASC",
                (task_id,),
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "task_id": row["task_id"],
                    "quality_score": row["quality_score"],
                    "issues": json.loads(row["issues"]) if row["issues"] else [],
                    "human_feedback": json.loads(row["human_feedback"]) if row["human_feedback"] else None,
                    "created_at": row["created_at"],
                    "audit_type": row["audit_type"]
                }
                for row in rows
            ]

    # ---- 自定义序列化：只存非 None 字段，不依赖 asdict ----
    @staticmethod
    def _serialize_results(results: List[TaskResult]) -> list:
        return [
            {"type": r.type, "url": r.url, "content": r.content}
            for r in results
        ]

    @staticmethod
    def _serialize_call_chain(chain: List[CallChainEntry]) -> list:
        return [
            {"model_name": c.model_name, "capability": c.capability,
             "status": c.status, "error_code": c.error_code,
             "attempted_at": c.attempted_at,
             # 多 Agent 可观测性字段（工单 T-01）：
             # 落库侧必须同步补齐，否则历史任务回放看不到角色名
             "agent": getattr(c, "agent", ""),
             "elapsed_ms": getattr(c, "elapsed_ms", 0)}
            for c in chain
        ]

    def save_task_log(
        self, task_id: str, session_id: str,
        frontend: dict, log: dict,
        results: Optional[List[TaskResult]] = None,
        call_chain: Optional[List[CallChainEntry]] = None,
        user_input: str = "",
    ) -> None:
        """保存任务日志（results / call_chain 接受 dataclass 对象列表）"""
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO task_logs "
                    "(task_id, session_id, task_status, frontend_json, log_json, "
                    " results_json, call_chain_json, user_input, internal_task_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        task_id,
                        session_id,
                        log.get("task_status", "UNKNOWN"),
                        json.dumps(frontend, ensure_ascii=False),
                        json.dumps(log, ensure_ascii=False),
                        json.dumps(self._serialize_results(results or []), ensure_ascii=False),
                        json.dumps(self._serialize_call_chain(call_chain or []), ensure_ascii=False),
                        user_input,
                        # 引擎内部 task_id（agent_messages 的归属键）。
                        # 持久化后，即使 Redis 映射过期也能关联多 Agent 轨迹。
                        (log or {}).get("task_id"),
                    ),
                )
        except Exception:
            pass  # 写入失败不阻断主流程

    # ---- 会话元数据 ----
    def save_session(self, session_id: str, label: str = "新对话") -> None:
        """保存会话元数据（标签）到 sessions 表"""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sessions (session_id, label) VALUES (?, ?)",
                (session_id, label),
            )

    def ensure_session(self, session_id: str, label: str = "新对话") -> bool:
        """会话不存在时登记（submit 兜底调用），已存在则不动。返回是否新登记"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            self.save_session(session_id, label)
            return True
        return False

    def rename_session(self, session_id: str, label: str) -> bool:
        """重命名会话。会话不存在返回 False"""
        with self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE sessions SET label = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE session_id = ?",
                (label, session_id),
            )
            return cur.rowcount > 0

    def get_session_label(self, session_id: str) -> Optional[str]:
        """读取会话当前标签；会话未登记返回 None"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT label FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            return row["label"] if row else None

    def backfill_session_label(self, session_id: str, user_input: str) -> None:
        """用首条用户消息回填会话标签（仅当仍为默认'新对话'，不覆盖用户自定义名）"""
        label = self.get_session_label(session_id)
        if label == "新对话" and user_input:
            self.rename_session(session_id, user_input[:30])


    def delete_messages(self, session_id:str)-> None:
        """删除某个会话的全部消息"""
        with self._get_conn()as conn:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))

    def delete_task_history(self, session_id: str) -> None:
        """删除某个会话的日志调用"""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM task_logs WHERE session_id = ?", (session_id,))

    def delete_session_data(self, session_id: str) -> None:
        """删除会话相关的全部持久数据（含会话元数据与审计记录）"""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM task_logs WHERE session_id = ?", (session_id,))

    def delete_session_audits(self, session_id: str) -> None:
        """删除会话下所有任务的审计记录（task_audits 以 task_id 关联，需先取任务ID）"""
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM task_audits WHERE task_id IN "
                "(SELECT task_id FROM task_logs WHERE session_id = ?)",
                (session_id,),
            )

    def list_sessions(self) -> List[dict]:
        """列出所有会话,按创建时间降序。返回 [{session_id, label, created_at}]"""
        with self._get_conn() as conn:
            # 以 sessions 表为主，关联消息/任务日志统计
            rows = conn.execute("""
                SELECT s.session_id, s.label, s.created_at
                FROM sessions s
                ORDER BY s.created_at DESC
            """).fetchall()
            if rows:
                return [{"session_id": r["session_id"], "label": r["label"],
                         "created_at": r["created_at"]} for r in rows]
            # 兼容无 sessions 表的旧数据：从 messages / task_logs 提取
            rows = conn.execute("""
                SELECT session_id, MIN(created_at) AS created_at FROM (
                    SELECT session_id, created_at FROM messages
                    UNION ALL
                    SELECT session_id, created_at FROM task_logs
                ) GROUP BY session_id ORDER BY created_at DESC
            """).fetchall()
            result = []
            for r in rows:
                row2 = conn.execute(
                    "SELECT content FROM messages WHERE session_id = ? AND role = 'user' "
                    "ORDER BY created_at ASC LIMIT 1", (r["session_id"],)
                ).fetchone()
                result.append({
                    "session_id": r["session_id"],
                    "label": (row2["content"] if row2 else "新对话")[:30],
                    "created_at": r["created_at"],
                })
            return result

    def get_first_message(self, session_id: str) -> str:
        """取某个会话最早的用户消息，用作会话标签"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT content FROM messages WHERE session_id = ? AND role = 'user' "
                "ORDER BY created_at ASC LIMIT 1",
                (session_id,),
            ).fetchone()
            return row["content"] if row else "新对话"

    def get_task_history(self, session_id: str, limit: int = 10) -> List[dict]:
        """获取某个会话的任务历史（最近 N 条，含 user_input 与调用链，供前端恢复/回放）"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT task_id, task_status, frontend_json, log_json, call_chain_json, "
                "user_input, created_at "
                "FROM task_logs WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
            result = []
            for row in rows:
                frontend = json.loads(row["frontend_json"] or "{}")
                log = json.loads(row["log_json"] or "{}")
                results_data = frontend.get("data", {})

                # call_chain 优先取 log_json 内嵌的；缺失时回退到专用列
                # call_chain_json，避免历史数据回放丢失调用链
                chain_src = log.get("call_chain") or json.loads(row["call_chain_json"] or "[]")
                result.append({
                    "task_id": row["task_id"],
                    "task_status": row["task_status"],
                    "created_at": row["created_at"],
                    "user_input": row["user_input"] or "",
                    "summary": results_data.get("results", []),
                    # 归一化：老日志的 call_chain 缺 agent/elapsed_ms 键，
                    # 直接透传会导致前端取值 KeyError（工单 T-01）
                    "call_chain": [
                        {
                            "model_name": e.get("model_name", ""),
                            "capability": e.get("capability", ""),
                            "status": e.get("status", ""),
                            "error_code": e.get("error_code"),
                            "attempted_at": e.get("attempted_at", ""),
                            "agent": e.get("agent", ""),
                            "elapsed_ms": e.get("elapsed_ms", 0),
                        }
                        for e in (chain_src or [])
                    ],
                    "error_summary": log.get("error_summary", []),
                })
            return result

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
                session_id=session_id,
                final_status=row["task_status"],
                results=[TaskResult(**r) for r in json.loads(results_raw)],
                call_chain=[CallChainEntry(**c) for c in json.loads(chain_raw)],
            )

    # ==================================================================
    # 多 Agent 交互痕迹（升级计划 4.5 / 阶段一）
    # 记录 Orchestrator 与各专业 Agent 之间的消息与工件交换，
    # 供论文做协作过程可观测性分析与前端链路回放。
    # ==================================================================
    def save_agent_message(
        self,
        task_id: str,
        session_id: str,
        from_agent: str,
        to_agent: str,
        step: int = 0,
        message_type: str = "dispatch",
        content: str = "",
        artifacts: Optional[List[dict]] = None,
        status: Optional[str] = None,
        issues: Optional[List[str]] = None,
        role: Optional[str] = None,
        reference_step: Optional[int] = None,
    ) -> None:
        """保存一条 Agent 间消息。写入失败不阻断主流程（与既有风格一致）

        role（T-13）：本消息的**执行方** Agent 名。派发消息的执行方是 to_agent，
        回收消息的执行方是 from_agent。落库时写明，前端直接读取，
        不必再按 message_type 反推（消除前后端各维护一份推导逻辑的隐患）。

        reference_step（T-12）：本步骤依赖的上游步骤号，用于还原产物依赖链。
        """
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT INTO agent_messages "
                    "(task_id, session_id, from_agent, to_agent, step, "
                    " message_type, content, artifacts, status, issues, "
                    " role, reference_step) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        task_id,
                        session_id,
                        from_agent,
                        to_agent,
                        step,
                        message_type,
                        content or "",
                        json.dumps(artifacts or [], ensure_ascii=False),
                        status,
                        json.dumps(issues, ensure_ascii=False) if issues else None,
                        role,
                        reference_step,
                    ),
                )
        except Exception:
            pass  # 审计类写入静默失败，不影响任务执行

    def resolve_internal_task_id(self, external_task_id: str) -> Optional[str]:
        """由外部（队列）任务 ID 解析引擎内部 task_id。

        持久化来源：task_logs.internal_task_id。
        设计动机：该映射原先只写在 Redis（TTL 1 小时），过期或 Redis 被清空后，
        历史任务的 Agent 协作轨迹（agent_messages 按内部 ID 存储）将无法关联，
        表现为"任务的协作拓扑/对话流打开后是空的"。
        现以 SQLite 为权威来源，Redis 仅作快速路径。
        """
        try:
            with self._get_conn() as conn:
                row = conn.execute(
                    "SELECT internal_task_id FROM task_logs WHERE task_id = ?",
                    (external_task_id,),
                ).fetchone()
            if row and row["internal_task_id"]:
                return row["internal_task_id"]
        except Exception:
            pass
        return None

    def get_agent_messages(self, task_id: str, limit: int = 100) -> List[dict]:
        """按步骤顺序取某任务的全部 Agent 消息"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_messages WHERE task_id = ? "
                "ORDER BY step ASC, id ASC LIMIT ?",
                (task_id, limit),
            ).fetchall()
            return [
                {
                    "task_id": r["task_id"],
                    "session_id": r["session_id"],
                    "from_agent": r["from_agent"],
                    "to_agent": r["to_agent"],
                    "step": r["step"],
                    "message_type": r["message_type"],
                    "content": r["content"] or "",
                    "artifacts": json.loads(r["artifacts"] or "[]"),
                    "status": r["status"],
                    "issues": json.loads(r["issues"]) if r["issues"] else None,
                    # role（T-13）与 reference_step（T-12）：老库经 _check_columns 补列后均可读
                    "role": r["role"] if "role" in r.keys() else None,
                    "reference_step": (r["reference_step"]
                                       if "reference_step" in r.keys() else None),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]

    def get_session_agent_messages(self, session_id: str, limit: int = 100) -> List[dict]:
        """取某会话下所有 Agent 消息（跨任务，用于会话级协作过程回放）

        注意: DISTINCT 必需 —— 同一 task_id 下会有多条消息，
        若直接按行遍历会导致同一批消息被重复展开。
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT task_id FROM agent_messages WHERE session_id = ? "
                "ORDER BY task_id",
                (session_id,),
            ).fetchall()
        out: List[dict] = []
        for r in rows:
            out.extend(self.get_agent_messages(r["task_id"]))
        return out
