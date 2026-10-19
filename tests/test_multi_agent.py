"""多 Agent 阶段一（协议与数据层）单元测试

覆盖:
- Artifact 四类产物的构造与序列化往返
- AgentMessage / AgentResponse 契约往返
- TaskContext 的产物传递与重试计数（防死循环）
- BaseAgent 的路由、降级重试、异常兜底
- Storage 的 agent_messages 落库与查询
- Memory 的 Agent 维度隔离
- MessageBus 的星型派发与产物汇总
"""
import os
import tempfile

import pytest

from src.core.contracts import (
    Artifact,
    AgentMessage,
    AgentResponse,
    TaskContext,
    STATUS_SUCCESS,
    STATUS_FAILED,
    STATUS_NEED_REVISION,
    ARTIFACT_TEXT,
    ARTIFACT_IMAGE,
    ARTIFACT_VIDEO,
)
from src.core.base_agent import BaseAgent
from src.core.message_bus import MessageBus
from src.core.memory import Memory
from src.core.storage import Storage
from src.core.models import ModelInfo
from src.core.router import Router


# ==================================================================
# Artifact
# ==================================================================
def test_artifact_factories_and_roundtrip():
    a_img = Artifact.image_of("https://x/img.png", step=1, model="Z-Image")
    a_txt = Artifact.text_of("一段文案", step=2)
    a_vid = Artifact.video_of("https://x/v.mp4", step=3)

    assert (a_img.type, a_txt.type, a_vid.type) == (
        ARTIFACT_IMAGE, ARTIFACT_TEXT, ARTIFACT_VIDEO
    )
    assert a_img.metadata["model"] == "Z-Image"

    restored = Artifact.from_dict(a_img.to_dict())
    assert restored == a_img


def test_artifact_converts_to_legacy_task_result():
    """Artifact 必须能回流到存量 Builder/Storage 链路"""
    from src.core.models import TaskResult

    img = Artifact.image_of("https://x/i.png").to_task_result()
    assert isinstance(img, TaskResult) and img.type == "image" and img.url == "https://x/i.png"

    txt = Artifact.text_of("正文").to_task_result()
    assert txt.type == "text" and txt.content == "正文"

    vid = Artifact.video_of("https://x/v.mp4").to_task_result()
    assert vid.type == "video" and vid.url == "https://x/v.mp4"


# ==================================================================
# AgentMessage / AgentResponse
# ==================================================================
def test_agent_message_carries_upstream_artifacts():
    msg = AgentMessage(
        task_id="t1", step=2, sender="orchestrator", receiver="writer_agent",
        prompt="根据图片写文案", capability="text-generation", session_id="s1",
        artifacts=[Artifact.image_of("https://x/i.png"), Artifact.text_of("上游草稿")],
    )
    assert len(msg.artifacts_of_type(ARTIFACT_IMAGE)) == 1
    assert msg.first_image_url == "https://x/i.png"
    assert len(msg.artifacts_of_type(ARTIFACT_VIDEO)) == 0

    back = AgentMessage.from_dict(msg.to_dict())
    assert back.receiver == "writer_agent" and len(back.artifacts) == 2


def test_agent_response_states():
    ok = AgentResponse.success("writer_agent", artifacts=[Artifact.text_of("x")], output_text="x")
    bad = AgentResponse.failed("writer_agent", error_code=408, issues=["超时"])
    rev = AgentResponse.need_revision("reviewer_agent", issues=["文案太短"])

    assert ok.ok is True
    assert bad.ok is False and bad.error_code == 408
    assert rev.status == STATUS_NEED_REVISION
    assert AgentResponse.from_dict(rev.to_dict()).issues == ["文案太短"]


# ==================================================================
# TaskContext：解决"步骤间产物传递 + 防死循环"
# ==================================================================
def test_task_context_passes_text_artifacts_downstream():
    """这是现状 step_outputs 做不到的能力：文本产物也能传给下游"""
    ctx = TaskContext(task_id="t1", session_id="s1")
    ctx.record(1, [Artifact.image_of("https://x/i.png")])
    ctx.record(2, [Artifact.text_of("火星探险日记正文")])

    upstream_of_3 = ctx.upstream_of(3)
    assert len(upstream_of_3) == 2
    assert any(a.type == ARTIFACT_TEXT for a in upstream_of_3)


def test_task_context_retry_budget_limits_loop():
    ctx = TaskContext(task_id="t1", max_retries=2)
    assert ctx.can_retry(1) is True
    ctx.bump(1); ctx.bump(1)
    assert ctx.can_retry(1) is False      # 用尽预算，拒绝继续
    assert ctx.can_retry(2) is True       # 不同步骤独立计数


# ==================================================================
# BaseAgent
# ==================================================================
class _FakeLLM:
    """按 model_name 决定成功/失败，模拟主模型挂掉备选接棒"""

    def __init__(self, fail_models=()):
        self.fail_models = set(fail_models)
        self.calls = []

    def call(self, model_name, endpoint, api_key, prompt, output_type, image_url=""):
        self.calls.append(model_name)
        if model_name in self.fail_models:
            return AgentResponse.failed("llm", error_code=503)
        return AgentResponse.success("llm", artifacts=[Artifact.text_of(prompt)])


class _EchoAgent(BaseAgent):
    """模拟真实 Agent：真正走 LLMClient，才能验证基类的降级重试"""

    default_capability = "text-generation"

    def _run(self, message, context, model_info):
        self.model_invoked = True
        resp = self.llm_client.call(
            model_name=model_info["model_name"],
            endpoint=model_info["endpoint"],
            api_key=model_info["api_key"],
            prompt=message.prompt,
            output_type="text",
        )
        if not resp.ok:
            return AgentResponse.failed(self.name, error_code=resp.error_code)
        return AgentResponse.success(
            self.name, artifacts=[Artifact.text_of(resp.artifacts[0].content)]
        )


def _router():
    return Router([
        ModelInfo("primary", "model-A", "e", "k", "text-generation"),
        ModelInfo("backup", "model-B", "e", "k", "text-generation"),
    ])


def test_base_agent_success_records_call_chain():
    agent = _EchoAgent("writer_agent", _router(), _FakeLLM())
    ctx = TaskContext(task_id="t1")
    msg = AgentMessage(task_id="t1", step=1, sender="orchestrator",
                       receiver="writer_agent", prompt="写文案")

    resp = agent.execute(msg, ctx)

    assert resp.ok
    assert resp.artifacts[0].content == "写文案"
    chain = agent.drain_call_chain()
    assert len(chain) == 1 and chain[0].status == "SUCCESS"
    assert agent.drain_call_chain() == []      # 取走后清空


def test_base_agent_falls_back_to_backup_model():
    """主模型失败应自动降级到备选模型（重试预算允许时）"""
    llm = _FakeLLM(fail_models={"model-A"})
    agent = _EchoAgent("writer_agent", _router(), llm)
    ctx = TaskContext(task_id="t1", max_retries=2)
    msg = AgentMessage(task_id="t1", step=1, sender="orchestrator",
                       receiver="writer_agent", prompt="p")

    resp = agent.execute(msg, ctx)

    assert resp.ok
    assert llm.calls == ["model-A", "model-B"]   # 确实换了模型
    chain = agent.drain_call_chain()
    assert [c.status for c in chain] == ["FAILED", "SUCCESS"]


def test_base_agent_stops_when_retry_budget_exhausted():
    """所有模型都失败且预算用尽时返回失败，不无限重试"""
    llm = _FakeLLM(fail_models={"model-A", "model-B"})
    agent = _EchoAgent("writer_agent", _router(), llm)
    ctx = TaskContext(task_id="t1", max_retries=1)
    msg = AgentMessage(task_id="t1", step=1, sender="orchestrator",
                       receiver="writer_agent", prompt="p")

    resp = agent.execute(msg, ctx)

    assert resp.ok is False
    assert resp.status == STATUS_FAILED
    assert len(agent.drain_call_chain()) == 2    # 两个模型各试一次即止


def test_base_agent_converts_exception_to_failed_response():
    class _Boom(_EchoAgent):
        def _run(self, message, context, model_info):
            raise RuntimeError("下游炸了")

    agent = _Boom("image_agent", _router(), _FakeLLM())
    ctx = TaskContext(task_id="t1", max_retries=0)
    msg = AgentMessage(task_id="t1", step=1, sender="orchestrator",
                       receiver="image_agent", prompt="p")

    resp = agent.execute(msg, ctx)

    assert resp.ok is False
    assert "下游炸了" in resp.issues[0]


def test_base_agent_reports_no_available_model():
    """模型注册表为空时给出语义化错误，而非裸 -2"""
    agent = _EchoAgent("writer_agent", Router([]), _FakeLLM())
    ctx = TaskContext(task_id="t1")
    msg = AgentMessage(task_id="t1", step=1, sender="orchestrator",
                       receiver="writer_agent", prompt="p")

    resp = agent.execute(msg, ctx)

    assert resp.ok is False
    assert "无可用模型" in resp.issues[0]


# ==================================================================
# Storage: agent_messages
# ==================================================================
@pytest.fixture()
def storage():
    tmp = tempfile.mktemp(suffix=".db")
    st = Storage(tmp)
    yield st
    if os.path.exists(tmp):
        os.remove(tmp)


def test_storage_agent_messages_roundtrip(storage):
    storage.save_agent_message(
        task_id="t1", session_id="s1", from_agent="orchestrator",
        to_agent="writer_agent", step=1, message_type="dispatch",
        content="写文案",
    )
    storage.save_agent_message(
        task_id="t1", session_id="s1", from_agent="writer_agent",
        to_agent="orchestrator", step=1, message_type="result",
        content="完成", artifacts=[{"type": "text", "content": "正文", "metadata": {}}],
        status="SUCCESS",
    )

    msgs = storage.get_agent_messages("t1")
    assert len(msgs) == 2
    assert msgs[0]["from_agent"] == "orchestrator"
    assert msgs[1]["status"] == "SUCCESS"
    assert msgs[1]["artifacts"][0]["content"] == "正文"


def test_storage_session_agent_messages_no_duplication(storage):
    """同一 task_id 多条消息，会话级查询不应重复展开"""
    for i in range(3):
        storage.save_agent_message(
            task_id="t1", session_id="s1", from_agent="a", to_agent="b",
            step=i, message_type="dispatch", content=str(i),
        )
    assert len(storage.get_session_agent_messages("s1")) == 3


# ==================================================================
# Memory: Agent 维度隔离
# ==================================================================
def test_memory_agent_scope_isolation():
    mem = Memory(max_history=5)
    mem.add("s1", "user", "生成一张图")
    mem.add_agent_message("s1", "image_agent", "assistant", "视觉提示词")
    mem.add_agent_message("s1", "writer_agent", "assistant", "写作要点")

    assert len(mem.get_agent_history("s1", "image_agent")) == 1
    assert len(mem.get_agent_history("s1", "writer_agent")) == 1
    # 私有默认不含公共对话历史
    assert mem.get_agent_history("s1", "writer_agent")[0].content == "写作要点"
    # 可显式合并公共历史
    assert len(mem.get_agent_history("s1", "writer_agent", include_public=True)) == 2


def test_memory_delete_session_clears_agent_scopes():
    mem = Memory()
    mem.add_agent_message("s1", "writer_agent", "assistant", "x")
    mem.delete_session("s1")
    assert mem.get_agent_history("s1", "writer_agent") == []


# ==================================================================
# MessageBus: 星型派发
# ==================================================================
def test_message_bus_dispatch_and_collect(storage):
    bus = MessageBus(storage=storage)
    bus.register(_EchoAgent("writer_agent", _router(), _FakeLLM()))

    ctx = TaskContext(task_id="t1", session_id="s1")
    msg = AgentMessage(task_id="t1", step=1, sender="orchestrator",
                       receiver="writer_agent", prompt="p1", session_id="s1")

    r1 = bus.dispatch(msg, ctx)
    assert r1.ok

    msg2 = AgentMessage(task_id="t1", step=2, sender="orchestrator",
                        receiver="writer_agent", prompt="p2",
                        artifacts=bus.collect_artifacts([r1]), session_id="s1")
    r2 = bus.dispatch(msg2, ctx)
    assert r2.ok

    # 上游产物确实传到了下游
    assert msg2.artifacts[0].content == "p1"
    trace = bus.drain_trace()
    assert len(trace) == 4                     # 两次 dispatch 各记 派发+回收
    assert bus.drain_trace() == []


def test_message_bus_unregistered_agent_returns_failure(storage):
    bus = MessageBus(storage=storage)
    ctx = TaskContext(task_id="t1", session_id="s1")
    msg = AgentMessage(task_id="t1", step=1, sender="orchestrator",
                       receiver="ghost_agent", prompt="p", session_id="s1")

    resp = bus.dispatch(msg, ctx)
    assert resp.ok is False
    assert "未注册" in resp.issues[0]


def test_message_bus_persists_trace(storage):
    bus = MessageBus(storage=storage)
    bus.register(_EchoAgent("writer_agent", _router(), _FakeLLM()))
    ctx = TaskContext(task_id="t1", session_id="s1")
    bus.dispatch(
        AgentMessage(task_id="t1", step=1, sender="orchestrator",
                     receiver="writer_agent", prompt="p", session_id="s1"),
        ctx,
    )
    persisted = storage.get_agent_messages("t1")
    assert len(persisted) == 2          # dispatch + result 均落库
    assert persisted[0]["message_type"] == "dispatch"
    assert persisted[1]["message_type"] == "result"
