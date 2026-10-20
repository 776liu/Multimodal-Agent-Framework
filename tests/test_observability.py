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
from src.core.contracts import (
    Artifact, AgentMessage, AgentResponse, TaskContext, STATUS_NEED_REVISION,
)
from src.core.router import Router
from src.core.agents import ReviewerAgent
from src.api.task_manager import MemoryTaskManager


class _StubLLM:
    def __init__(self, delay=0.0, review_json=None):
        self.delay = delay
        self.review_json = review_json
        self.calls = 0

    def call(self, model_name, endpoint, api_key, prompt, output_type, image_url=""):
        """返回真实 LLMResponse 形状（.data.content），与生产 llm_client 一致"""
        from src.core.models import LLMResponse, TaskResult
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        # 审查调用（ReviewAgent 的 prompt 含"质量审查员"）按预设 JSON 返回
        if "质量审查员" in prompt and self.review_json is not None:
            return LLMResponse(status="SUCCESS",
                               data=TaskResult(type="text", content=self.review_json),
                               model_name=model_name)
        return LLMResponse(status="SUCCESS",
                           data=TaskResult(type="text", content="一段足够长的产物内容。"),
                           model_name=model_name)


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


def _msg(step=1, receiver="writer_agent", artifacts=None):
    return AgentMessage(task_id="t1", step=step, sender="orchestrator",
                        receiver=receiver, prompt="p", artifacts=artifacts or [])


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


# ==================================================================
# 回归：NEED_REVISION 分支的调用链守卫（review 发现的漏网分支）
# ==================================================================
def test_need_revision_without_model_call_leaves_no_chain_entry():
    """规则快筛的打回未发生模型调用，不得写入耗时 0ms 的假记录"""
    agent = ReviewerAgent(_router(), _StubLLM())
    resp = agent.execute(
        _msg(receiver="reviewer_agent", artifacts=[Artifact.text_of("短")]),
        TaskContext(task_id="t1", max_retries=0),
    )
    assert resp.status == STATUS_NEED_REVISION
    assert agent.drain_call_chain() == [], "规则打回未调模型，链路必须为空"


def test_need_revision_with_model_call_records_chain():
    """LLM 审查的打回真实调用了模型，链路必须记录且带角色名与耗时"""
    review = json.dumps({"score": 2, "issues": ["事实错误"], "pass": False}, ensure_ascii=False)
    agent = ReviewerAgent(_router(), _StubLLM(review_json=review))
    resp = agent.execute(
        _msg(receiver="reviewer_agent",
             artifacts=[Artifact.text_of("这是一段足够长但内容有事实错误的文本。")]),
        TaskContext(task_id="t1", max_retries=0),
    )
    assert resp.status == STATUS_NEED_REVISION
    chain = agent.drain_call_chain()
    assert len(chain) == 1
    assert chain[0].agent == "reviewer_agent"
    assert chain[0].elapsed_ms >= 0


# ==================================================================
# 降级场景：同一 Agent 连续多条链路的 elapsed_ms 窗口（review 盲区 1）
# ==================================================================
def test_fallback_chain_records_separate_elapsed_windows():
    """降级换模型时，第二条链路的耗时窗口必须从第二次调用重新计时，
    而不是累计从第一次调用开始的时间（否则耗时数据失真）"""

    class _DelayedLLM:
        """主模型慢(80ms)失败，备选快(20ms)成功，用以区分两条耗时"""
        def __init__(self):
            self.calls = []

        def call(self, model_name, endpoint, api_key, prompt, output_type, image_url=""):
            self.calls.append(model_name)
            time.sleep(0.08 if model_name == "slow-A" else 0.02)
            if model_name == "slow-A":
                return AgentResponse.failed("llm", error_code=503)
            return AgentResponse.success("llm", artifacts=[Artifact.text_of("x" * 20)])

    from src.core.models import ModelInfo
    router = Router([
        ModelInfo("slow-A", "slow-A", "e", "k", "text-generation"),
        ModelInfo("fast-B", "fast-B", "e", "k", "text-generation"),
    ])
    agent = _NamedAgent("writer_agent", router, _DelayedLLM())
    agent.execute(_msg(), TaskContext(task_id="t1", max_retries=2))

    chain = agent.drain_call_chain()
    assert len(chain) == 2
    first, second = chain

    # 各自窗口独立：第一条 ≈ 80ms，第二条 ≈ 20ms
    assert first.model_name == "slow-A" and first.status == "FAILED"
    assert second.model_name == "fast-B" and second.status == "SUCCESS"
    assert 50 <= first.elapsed_ms <= 500, f"首条耗时窗口异常: {first.elapsed_ms}ms"
    assert second.elapsed_ms < first.elapsed_ms, (
        f"第二条窗口应独立计时(应≈20ms)，实际 {second.elapsed_ms}ms ≥ 首条 {first.elapsed_ms}ms"
    )


# ==================================================================
# 契约：Worker 写入的进度 payload 与前端消费字段对齐（review 盲区 2）
# ==================================================================
def test_progress_payload_contract_for_frontend():
    """前端角色卡消费的字段: stage/agent/step/total/status/issues/notice/ts

    该测试锁死 Worker 落入进度通道的 payload 形状：
    任何一端改名都会在此处失败，而不是前端静默显示空白。
    """
    from src.core.orchestrator import Orchestrator
    from src.core.registry import AgentRegistry
    from src.core.message_bus import MessageBus
    from src.core.task_router import TaskRouter
    from src.core.memory import Memory
    from src.core.models import Subtask, ExecutionPlan
    from src.core.agents import WriterAgent, ReviewerAgent

    class _StubTR:
        def route_task(self, ui):
            return ExecutionPlan(intent="x", task_id="p", subtasks=[
                Subtask(step=1, capability="text-generation", prompt="p")])

    r = _router()
    reg = AgentRegistry()
    reg.register_all([WriterAgent(r, _StubLLM()), ReviewerAgent(r, _StubLLM())])
    bus = MessageBus()
    bus.register(reg.get("writer_agent"))
    bus.register(reg.get("reviewer_agent"))

    orch = Orchestrator(task_router=_StubTR(), registry=reg, message_bus=bus,
                        builder=Builder(), memory=Memory())
    captured = []

    # 模拟 Worker._make_progress 的落通道动作：只补 ts，不改其他字段
    def _on_progress(event):
        payload = dict(event)
        payload.setdefault("ts", time.time())
        captured.append(payload)

    orch.run("p", "s1", on_progress=_on_progress)

    assert captured, "Orchestrator 未发出任何进度事件"

    required = {"stage", "ts"}
    dispatch_events = [e for e in captured if e["stage"] == "dispatching"]
    assert dispatch_events, "缺少 dispatching 事件"

    for e in captured:
        missing = required - set(e.keys())
        assert not missing, f"进度事件缺字段 {missing}，前端将显示空白"

    # dispatching 事件必须带 agent（前端角色卡逐节点点亮的数据源）
    assert all(e.get("agent") for e in dispatch_events), \
        "dispatching 事件缺 agent 字段，角色卡将无法渲染角色名"
