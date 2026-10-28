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
