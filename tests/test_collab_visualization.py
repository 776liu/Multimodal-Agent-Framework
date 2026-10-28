"""协作可视化数据链路测试（工单 T-12 / T-13）

验证后端把"依赖关系"与"执行方角色"透出到持久层与 API：
- T-12：ReferenceStep 从计划 → AgentMessage → agent_messages 表 → /agents 响应
- T-13：role 字段落库，前端无需按 message_type 反推执行方
"""
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.contracts import (Artifact, AgentMessage, AgentResponse, TaskContext)
from src.core.message_bus import MessageBus
from src.core.storage import Storage


class _EchoAgent:
    """最小 Agent：回写一个文本产物"""
    name = "echo_agent"

    def __init__(self, text="产物内容足够长以通过规则审查"):
        self.text = text
        self.call_chains = []

    def execute(self, message, context):
        return AgentResponse.success(
            self.name,
            artifacts=[Artifact.text_of(self.text, step=message.step)],
            output_text=self.text,
        )

    def drain_call_chain(self):
        return []


def _make(tmpdir):
    storage = Storage(db_path=os.path.join(tmpdir, "t.db"))
    return storage, MessageBus(storage=storage)


# ----------------------------------------------------------------------
# T-12：reference_step 全链路透传
# ----------------------------------------------------------------------
def test_reference_step_persisted_to_db():
    with tempfile.TemporaryDirectory() as d:
        storage, bus = _make(d)
        bus.register(_EchoAgent())
        ctx = TaskContext(task_id="t1", session_id="s1", user_input="")

        msg = AgentMessage(task_id="t1", step=2, sender="orchestrator",
                           receiver="echo_agent", prompt="写文案",
                           capability="text-generation", session_id="s1",
                           reference_step=1)
        bus.dispatch(msg, ctx)

        rows = storage.get_agent_messages("t1")
        assert rows, "应落库至少一条消息"
        assert all(r["reference_step"] == 1 for r in rows), \
            f"reference_step 应全为 1，实际 {[r['reference_step'] for r in rows]}"


def test_no_reference_step_stays_none():
    """无依赖的步骤不应被赋默认值（否则前端会画出错误的连线）"""
    with tempfile.TemporaryDirectory() as d:
        storage, bus = _make(d)
        bus.register(_EchoAgent())
        ctx = TaskContext(task_id="t2", session_id="s1", user_input="")

        msg = AgentMessage(task_id="t2", step=1, sender="orchestrator",
                           receiver="echo_agent", prompt="翻译",
                           session_id="s1")
        bus.dispatch(msg, ctx)

        rows = storage.get_agent_messages("t2")
        assert all(r["reference_step"] is None for r in rows)


def test_agent_message_roundtrip_keeps_reference_step():
    """to_dict / from_dict 往返不丢失 reference_step"""
    msg = AgentMessage(task_id="t", step=2, sender="orchestrator",
                       receiver="writer_agent", prompt="p", reference_step=1)
    restored = AgentMessage.from_dict(msg.to_dict())
    assert restored.reference_step == 1

    # None 也要能往返
    msg2 = AgentMessage(task_id="t", step=1, sender="o", receiver="w", prompt="p")
    assert AgentMessage.from_dict(msg2.to_dict()).reference_step is None


def test_reference_step_zero_preserved():
    """reference_step=0 表示引用对话历史产物，不能被当成 None 丢掉"""
    msg = AgentMessage(task_id="t", step=1, sender="o", receiver="w",
                       prompt="p", reference_step=0)
    assert AgentMessage.from_dict(msg.to_dict()).reference_step == 0


# ----------------------------------------------------------------------
# T-13：role 字段落库（执行方）
# ----------------------------------------------------------------------
def test_role_recorded_for_dispatch_and_result():
    with tempfile.TemporaryDirectory() as d:
        storage, bus = _make(d)
        bus.register(_EchoAgent())
        ctx = TaskContext(task_id="t3", session_id="s1", user_input="")

        msg = AgentMessage(task_id="t3", step=1, sender="orchestrator",
                           receiver="echo_agent", prompt="写点东西", session_id="s1")
        bus.dispatch(msg, ctx)

        rows = storage.get_agent_messages("t3")
        types = {r["message_type"] for r in rows}
        assert types == {"dispatch", "result"}, f"应有一次派发一次回收，实际 {types}"

        for r in rows:
            assert r["role"] == "echo_agent", \
                f"{r['message_type']} 消息的 role 应恒为执行方 echo_agent，实际 {r['role']}"


def test_role_consistent_with_semantics():
    """dispatch 的 role == to_agent；result 的 role == from_agent"""
    with tempfile.TemporaryDirectory() as d:
        storage, bus = _make(d)
        bus.register(_EchoAgent())
        ctx = TaskContext(task_id="t4", session_id="s1", user_input="")

        bus.dispatch(AgentMessage(task_id="t4", step=1, sender="orchestrator",
                                  receiver="echo_agent", prompt="p",
                                  session_id="s1"), ctx)

        for r in storage.get_agent_messages("t4"):
            if r["message_type"] == "dispatch":
                assert r["role"] == r["to_agent"]
            else:
                assert r["role"] == r["from_agent"]


# ----------------------------------------------------------------------
# 旧库平滑升级
# ----------------------------------------------------------------------
def test_old_db_gets_new_columns():
    """模拟老库（无 role / reference_step 列），Storage 初始化后应自动补列"""
    import sqlite3
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "old.db")
        conn = sqlite3.connect(db)
        conn.execute("""
            CREATE TABLE agent_messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                from_agent TEXT NOT NULL,
                to_agent TEXT NOT NULL,
                step INTEGER DEFAULT 0,
                message_type TEXT NOT NULL,
                content TEXT,
                artifacts TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("INSERT INTO agent_messages(task_id, from_agent, to_agent, "
                     "message_type) VALUES ('old', 'a', 'b', 'dispatch')")
        conn.commit()
        conn.close()

        storage = Storage(db_path=db)   # 触发 _check_columns

        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        cols = {r["name"] for r in conn.execute(
            "PRAGMA table_info(agent_messages)").fetchall()}
        conn.close()

        assert "role" in cols, "老库应被补上 role 列"
        assert "reference_step" in cols, "老库应被补上 reference_step 列"

        # 老数据仍可读，新字段为 None
        rows = storage.get_agent_messages("old")
        assert len(rows) == 1
        assert rows[0]["role"] is None
        assert rows[0]["reference_step"] is None


# ----------------------------------------------------------------------
# 外部 ID → 内部 ID 映射持久化（协作视图长期可用）
# ----------------------------------------------------------------------
def test_internal_task_id_persisted_in_task_logs():
    """save_task_log 应把 log 里的内部 task_id 落进 internal_task_id 列"""
    with tempfile.TemporaryDirectory() as d:
        storage = Storage(db_path=os.path.join(d, "map.db"))
        storage.save_task_log(
            task_id="ext-1", session_id="s1",
            frontend={"task_id": "ext-1", "data": {}},
            log={"task_id": "task_internal_1", "task_status": "SUCCESS",
                 "call_chain": []},
        )
        assert storage.resolve_internal_task_id("ext-1") == "task_internal_1"


def test_resolve_returns_none_for_unknown():
    with tempfile.TemporaryDirectory() as d:
        storage = Storage(db_path=os.path.join(d, "map2.db"))
        assert storage.resolve_internal_task_id("nope") is None


def test_old_task_logs_backfilled_on_upgrade():
    """老库无 internal_task_id 列时，初始化应从 log_json 回填。

    这是"Redis 映射过期后历史任务协作视图全空"的修复核心：
    映射的权威来源改为 SQLite，并对存量数据一次性回填。
    """
    import sqlite3
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "oldlogs.db")
        conn = sqlite3.connect(db)
        conn.execute("""
            CREATE TABLE task_logs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL UNIQUE,
                session_id TEXT DEFAULT 'default',
                task_status TEXT NOT NULL,
                frontend_json TEXT,
                log_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        log = json.dumps({"task_id": "task_old_internal", "task_status": "SUCCESS"})
        conn.execute(
            "INSERT INTO task_logs(task_id, session_id, task_status, log_json) "
            "VALUES ('ext-old', 's1', 'SUCCESS', ?)", (log,))
        conn.commit()
        conn.close()

        storage = Storage(db_path=db)   # 触发补列 + 回填

        assert storage.resolve_internal_task_id("ext-old") == "task_old_internal"


def test_agents_fallback_uses_sqlite_when_redis_miss():
    """Redis 映射失效时，/agents 的解析链应回退到 SQLite。

    直接验证解析逻辑：给一个 Redis 查不到的外部 ID，
    只要 task_logs 里有映射，就应解析出内部 ID 并查到 agent_messages。
    """
    with tempfile.TemporaryDirectory() as d:
        storage, bus = _make(d)
        bus.register(_EchoAgent())
        ctx = TaskContext(task_id="task_inner_9", session_id="s1", user_input="")

        bus.dispatch(AgentMessage(task_id="task_inner_9", step=1,
                                  sender="orchestrator", receiver="echo_agent",
                                  prompt="干活", session_id="s1"), ctx)
        storage.save_task_log(
            task_id="ext-9", session_id="s1",
            frontend={"task_id": "ext-9"},
            log={"task_id": "task_inner_9", "task_status": "SUCCESS", "call_chain": []},
        )

        resolved = storage.resolve_internal_task_id("ext-9")
        assert resolved == "task_inner_9"
        # 用解析出的内部 ID 能查到协作轨迹
        assert len(storage.get_agent_messages(resolved)) == 2


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"[PASS] {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"[FAIL] {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"[ERROR] {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n结果: {len(tests) - failed} 通过 / {failed} 失败")
    sys.exit(1 if failed else 0)
