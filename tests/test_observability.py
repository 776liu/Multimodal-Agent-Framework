"""工单 T-01：多 Agent 可观测性单元测试

覆盖:
- CallChainEntry 新增 agent / elapsed_ms 字段及老数据反序列化兼容
- BaseAgent 调用链写入角色名与耗时
- builder / storage 两处序列化均带新字段（落库侧是历史回放的前提）
- TaskManager 进度通道（内存实现）：写入、读取、上限保护
- Orchestrator 进度事件结构含 agent / step / total
"""
import json
import os
import tempfile
import time

import pytest

from src.core.models import CallChainEntry, BuilderInput
from src.core.builder import Builder
from src.core.storage import Storage
from src.core.base_agent import BaseAgent
from src.core.contracts import Artifact, AgentMessage, AgentResponse, TaskContext
from src.core.router import Router
from src.api.task_manager import MemoryTaskManager


class _StubLLM:
    def __init__(self, delay=0.0):
        self.delay = delay
        self.calls = 0

    def call(self, model_name, endpoint, api_key, prompt, output_type, image_url=""):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        return AgentResponse.success("llm", artifacts=[Artifact.text_of("一段足够长的产物内容。")])


class _NamedAgent(BaseAgent):
    default_capability = "text-generation"

    def _run(self, message, context, model_info):
        self.model_invoked = True
        self._mark_call_start()
        resp = self.llm_client.call(
            model_name=model_info["model_name"], endpoint=model_info["endpoint"],
            api_key=model_info["api_key"], prompt=message.prompt, output_type="text",
        )
        if not resp.ok:
            return AgentResponse.failed(self.name, error_code=resp.error_code)
        return AgentResponse.success(self.name, artifacts=resp.artifacts)


def _router():
    from src.core.models import ModelInfo
    return Router([ModelInfo("m1", "model-A", "e", "k", "text-generation")])


def _msg(step=1):
    return AgentMessage(task_id="t1", step=step, sender="orchestrator",
                        receiver="writer_agent", prompt="p")


# ==================================================================
# CallChainEntry 字段
# ==================================================================
def test_call_chain_entry_has_agent_and_elapsed():
    e = CallChainEntry(model_name="m", capability="text-generation", status="SUCCESS",
                       agent="writer_agent", elapsed_ms=1234)
    assert e.agent == "writer_agent"
    assert e.elapsed_ms == 1234


def test_call_chain_entry_defaults_keep_backward_compat():
    """老数据反序列化（只有5个字段）必须仍可用"""
    old = {"model_name": "m", "capability": "text-generation", "status": "SUCCESS",
           "error_code": None, "attempted_at": "123.0"}
    e = CallChainEntry(**old)
    assert e.agent == "" and e.elapsed_ms == 0


# ==================================================================
# BaseAgent 记录角色与耗时
# ==================================================================
def test_base_agent_chain_records_agent_and_elapsed():
    agent = _NamedAgent("writer_agent", _router(), _StubLLM(delay=0.05))
    agent.execute(_msg(), TaskContext(task_id="t1"))

    chain = agent.drain_call_chain()
    assert len(chain) == 1
    assert chain[0].agent == "writer_agent"
    assert chain[0].elapsed_ms >= 40      # 实际 sleep 了 50ms


def test_no_model_call_means_no_chain_entry():
    class _ShortCircuit(_NamedAgent):
        def _run(self, message, context, model_info):
            return AgentResponse.success(self.name)   # 未调模型

    agent = _ShortCircuit("reviewer_agent", _router(), _StubLLM())
    agent.execute(_msg(), TaskContext(task_id="t1"))
    assert agent.drain_call_chain() == []


# ==================================================================
# 两处序列化
# ==================================================================
def test_builder_serializes_agent_fields():
    entry = CallChainEntry(model_name="m", capability="text-generation", status="SUCCESS",
                           agent="image_agent", elapsed_ms=800)
    out = Builder().build(BuilderInput(task_id="t", session_id="s", final_status="SUCCESS",
                                       results=[], call_chain=[entry]))
    c = out["log_record"]["call_chain"][0]
    assert c["agent"] == "image_agent"
    assert c["elapsed_ms"] == 800


def test_storage_persists_agent_fields_for_history_replay():
    """落库侧必须同步补齐，否则历史任务回放看不到角色名"""
    tmp = tempfile.mktemp(suffix=".db")
    try:
        st = Storage(tmp)
        entry = CallChainEntry(model_name="m", capability="text-generation",
                               status="SUCCESS", agent="video_agent", elapsed_ms=330000)
        st.save_task_log("t1", "s1", {"task_status": "SUCCESS", "data": {}},
                         {"task_status": "SUCCESS"}, call_chain=[entry])

        import sqlite3
        row = sqlite3.connect(tmp).execute(
            "SELECT call_chain_json FROM task_logs WHERE task_id='t1'"
        ).fetchone()
        saved = json.loads(row[0])[0]
        assert saved["agent"] == "video_agent"
        assert saved["elapsed_ms"] == 330000

        # 历史回放路径也能取到
        hist = st.get_task_history("s1", limit=5)
        assert hist[0]["call_chain"][0]["agent"] == "video_agent"
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def test_storage_handles_legacy_chain_without_agent_key():
    """老日志缺 agent 键时用默认值兜底，不报错"""
    tmp = tempfile.mktemp(suffix=".db")
    try:
        st = Storage(tmp)
        st.save_task_log("t2", "s2", {"task_status": "SUCCESS", "data": {}},
                         {"task_status": "SUCCESS"})
        # 直接构造老格式数据再读取
        import sqlite3
        conn = sqlite3.connect(tmp)
        conn.execute(
            "INSERT INTO task_logs (task_id, session_id, task_status, frontend_json, "
            "log_json, call_chain_json, user_input) VALUES (?,?,?,?,?,?,?)",
            ("t3", "s3", "SUCCESS", '{"data":{}}',
             json.dumps({"task_status": "SUCCESS", "call_chain": [
                 {"model_name": "m", "capability": "c", "status": "SUCCESS"}]}),
             json.dumps([{"model_name": "m", "capability": "c", "status": "SUCCESS"}]), ""),
        )
        conn.commit()
        conn.close()

        hist = st.get_task_history("s3", limit=5)
        assert hist[0]["call_chain"][0]["agent"] == ""
        assert hist[0]["call_chain"][0]["elapsed_ms"] == 0
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# ==================================================================
# 进度通道
# ==================================================================
def test_memory_task_manager_progress_roundtrip():
    tm = MemoryTaskManager()
    tm.append_progress("t1", {"stage": "planning"})
    tm.append_progress("t1", {"stage": "dispatching", "agent": "writer_agent"})

    events = tm.get_progress("t1")
    assert [e["stage"] for e in events] == ["planning", "dispatching"]
    assert tm.get_progress("nonexistent") == []


def test_progress_channel_has_size_cap():
    tm = MemoryTaskManager()
    for i in range(600):
        tm.append_progress("t1", {"stage": "s", "i": i})
    assert len(tm.get_progress("t1")) <= 500


# ==================================================================
# Orchestrator 进度事件结构
# ==================================================================
def test_orchestrator_progress_events_carry_agent_dimension():
    from src.core.orchestrator import Orchestrator
    from src.core.registry import AgentRegistry
    from src.core.message_bus import MessageBus
    from src.core.task_router import TaskRouter
    from src.core.memory import Memory
    from src.core.models import Subtask, ExecutionPlan

    class _StubTR:
        def route_task(self, ui):
            return ExecutionPlan(intent="x", task_id="p", subtasks=[
                Subtask(step=1, capability="text-generation", prompt="p")])

    from src.core.agents import WriterAgent, ReviewerAgent
    r = _router()
    reg = AgentRegistry()
    reg.register_all([WriterAgent(r, _StubLLM()), ReviewerAgent(r, _StubLLM())])
    bus = MessageBus()
    bus.register(reg.get("writer_agent"))
    bus.register(reg.get("reviewer_agent"))

    orch = Orchestrator(task_router=_StubTR(), registry=reg, message_bus=bus,
                        builder=Builder(), memory=Memory())
    events = []
    orch.run("p", "s1", on_progress=events.append)

    stages = {e["stage"] for e in events}
    assert {"planning", "dispatching", "collecting", "auditing"} <= stages

    # 关键：派发/回收事件必须带 agent 字段（前端据此渲染角色卡）
    dispatch = [e for e in events if e["stage"] == "dispatching"]
    assert dispatch and dispatch[0]["agent"] == "writer_agent"
    assert "step" in dispatch[0] and "total" in dispatch[0]
    collect = [e for e in events if e["stage"] == "collecting"]
    assert collect and collect[0]["agent"] == "writer_agent"


# ==================================================================
# 任务ID映射（外部队列ID ↔ 引擎内部task_id）
# ==================================================================
def test_task_manager_id_mapping_roundtrip():
    tm = MemoryTaskManager()
    assert tm.resolve_internal_task_id("ext_1") == "ext_1"   # 无映射时回退
    tm.link_internal_task_id("ext_1", "task_internal")
    assert tm.resolve_internal_task_id("ext_1") == "task_internal"


@pytest.mark.skipif(
    pytest.importorskip is None, reason="skip marker"
)
def test_agents_endpoint_shape_uses_internal_id():
    """/agents 必须用内部ID查 agent_messages，否则前端拿外部ID查不到轨迹"""
    pytest.importorskip("fastapi")
    pytest.importorskip("redis")
    from src.api.main import get_task_agents

    resolved = {}

    class _FakeTM:
        def resolve_internal_task_id(self, ext):
            resolved["ext"] = ext
            return "task_internal_xyz"

    class _FakeStorage:
        def get_agent_messages(self, tid):
            resolved["queried"] = tid
            return [
                {"task_id": tid, "session_id": "s", "from_agent": "orchestrator",
                 "to_agent": "writer_agent", "step": 1, "message_type": "dispatch",
                 "content": "p", "artifacts": [], "status": None, "issues": None,
                 "created_at": "t"},
            ]

    class _Req:
        app = type("A", (), {"state": type("S", (), {
            "task_manager": _FakeTM(), "storage": _FakeStorage()})()})()

    import asyncio
    out = asyncio.get_event_loop().run_until_complete(
        get_task_agents("ext_task_1", _Req())
    )
    assert resolved["ext"] == "ext_task_1"
    assert resolved["queried"] == "task_internal_xyz"
    assert out["internal_task_id"] == "task_internal_xyz"
    assert out["roles"] == ["orchestrator", "writer_agent"]
    assert out["message_count"] == 1
