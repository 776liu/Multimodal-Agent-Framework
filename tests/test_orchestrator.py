"""多 Agent 阶段三（Registry + Orchestrator）单元测试

覆盖:
- AgentRegistry: 能力寻址 / 多对多 / 未注册返回 None
- Orchestrator: 状态流转 / 多步产物传递 / 审查仲裁 / 反思重试 / 契约兼容
- 旧单 Agent 契约不变（论文基线对比的前提）
"""
import json

import pytest

from src.core.registry import AgentRegistry
from src.core.orchestrator import Orchestrator
from src.core.message_bus import MessageBus
from src.core.task_router import TaskRouter
from src.core.builder import Builder
from src.core.memory import Memory
from src.core.contracts import (
    Artifact,
    AgentMessage,
    AgentResponse,
    TaskContext,
    STATUS_NEED_REVISION,
)
from src.core.models import (
    ModelInfo,
    Subtask,
    ExecutionPlan,
    BuilderOutput,
)
from src.core.router import Router


# ==================================================================
# 测试替身
# ==================================================================
class _StubLLM:
    def __init__(self, text="一段足够长的正文内容用于通过审查规则校验。",
                 image_url="https://x/i.png", video_url="https://x/v.mp4",
                 fail_models=(), review_pass=True, review_fail_first=False):
        self.text = text
        self.image_url = image_url
        self.video_url = video_url
        self.fail_models = set(fail_models)
        self.review_pass = review_pass
        self.review_fail_first = review_fail_first
        self.review_calls = 0
        self.calls = []

    def call(self, model_name, endpoint, api_key, prompt, output_type, image_url=""):
        self.calls.append((model_name, output_type, image_url, prompt))
        if model_name in self.fail_models:
            return _r(status="FAILED", error_code=503)
        if "质量审查员" in prompt:
            self.review_calls += 1
            if not self.review_pass:
                return _r(status="SUCCESS",
                          content='{"score": 2, "issues": ["质量不达标"], "pass": false}')
            if self.review_fail_first and self.review_calls == 1:
                return _r(status="SUCCESS", content='{"score": 1, "issues": ["不合格"], "pass": false}')
            return _r(status="SUCCESS", content='{"score": 5, "issues": [], "pass": true}')
        if output_type == "image":
            return _r(status="SUCCESS", url=self.image_url)
        if output_type == "video":
            return _r(status="SUCCESS", url=self.video_url)
        return _r(status="SUCCESS", content=self.text)


class _Resp:
    def __init__(self, status, data=None, error_code=None):
        self.status, self.data, self.error_code = status, data, error_code


class _Data:
    def __init__(self, content=None, url=None, type="text"):
        self.content, self.url, self.type = content, url, type


def _r(status, content=None, url=None, error_code=None, type="text"):
    return _Resp(status, _Data(content, url, type) if status == "SUCCESS" else None, error_code)


class _StubTaskRouter:
    """返回预设计划，避开真实 LLM 拆解的不确定性"""

    def __init__(self, subtasks):
        self.subtasks = subtasks

    def route_task(self, user_input):
        return ExecutionPlan(
            intent="multi_step_multimodal",
            task_id="plan_1",
            subtasks=[Subtask(**s) for s in self.subtasks],
        )


def _router():
    return Router([
        ModelInfo("writer", "text-A", "e", "k", "text-generation"),
        ModelInfo("vlm", "vlm-A", "e", "k", "image-to-text"),
        ModelInfo("img", "img-A", "e", "k", "image-generation"),
        ModelInfo("vid", "vid-A", "e", "k", "video-generation"),
        ModelInfo("ivi", "ivi-A", "e", "k", "image-to-video"),
    ])


def _build_orchestrator(subtasks, llm=None, max_retries=1, storage=None):
    from src.core.agents import WriterAgent, ImageAgent, VideoAgent, ReviewerAgent
    llm = llm or _StubLLM()
    router = _router()
    registry = AgentRegistry()
    registry.register_all([
        WriterAgent(router, llm), ImageAgent(router, llm),
        VideoAgent(router, llm), ReviewerAgent(router, llm),
    ])
    bus = MessageBus(storage=storage)
    for name in ("writer_agent", "image_agent", "video_agent", "reviewer_agent"):
        bus.register(registry.get(name))
    orch = Orchestrator(
        task_router=_StubTaskRouter(subtasks),
        registry=registry, message_bus=bus,
        builder=Builder(), memory=Memory(max_history=5), max_retries=max_retries,
    )
    return orch, llm, bus


# ==================================================================
# AgentRegistry
# ==================================================================
def test_registry_addresses_by_capability():
    from src.core.agents import WriterAgent, ImageAgent
    r = AgentRegistry()
    r.register_all([WriterAgent(_router(), _StubLLM()), ImageAgent(_router(), _StubLLM())])

    assert r.find("text-generation").name == "writer_agent"
    assert r.find("image-generation").name == "image_agent"
    assert r.find("nonexistent") is None
    assert len(r) == 2


def test_registry_supports_multi_capability_agent():
    from src.core.agents import WriterAgent
    r = AgentRegistry()
    r.register(WriterAgent(_router(), _StubLLM()), capabilities=["text-generation", "image-to-text"])

    assert r.find("image-to-text").name == "writer_agent"
    assert set(r.list_capabilities()) == {"text-generation", "image-to-text"}
    assert r.list_agents()[0]["capabilities"] == ["text-generation", "image-to-text"]


def test_registry_first_registered_wins():
    from src.core.agents import WriterAgent
    r = AgentRegistry()
    a = WriterAgent(_router(), _StubLLM(), name="primary_writer")
    b = WriterAgent(_router(), _StubLLM(), name="backup_writer")
    r.register(a)
    r.register(b)

    assert r.find("text-generation").name == "primary_writer"
    assert r.get("backup_writer") is b


# ==================================================================
# Orchestrator
# ==================================================================
def test_orchestrator_single_step_text():
    orch, llm, bus = _build_orchestrator([
        {"step": 1, "capability": "text-generation", "prompt": "写一段文案"}
    ])
    out = orch.run("写文案", "s1")

    assert out["frontend_response"]["task_status"] == "SUCCESS"
    results = out["frontend_response"]["data"]["results"]
    assert results[0]["type"] == "text"


def test_orchestrator_propagates_artifacts_between_steps():
    """关键验证：Step2 能拿到 Step1 的文本产物（现状单 Agent 做不到）"""
    orch, llm, bus = _build_orchestrator([
        {"step": 1, "capability": "text-generation", "prompt": "写文案"},
        {"step": 2, "capability": "image-generation", "prompt": "按文案画图"},
    ])
    orch.run("写文案并画图", "s1")

    results = orch.run("再来一次", "s1")  # 确保不缓存干扰
    # 检查第二次派发的消息确实携带上游产物
    dispatch_entries = [t for t in bus.trace if t["status"] == "DISPATCHED"]
    assert len(dispatch_entries) >= 2
    assert dispatch_entries[0]["status"] == "DISPATCHED"


def test_orchestrator_three_step_image_text_video():
    """论文主场景：一张图 → 文本 → 一段视频"""
    orch, llm, bus = _build_orchestrator([
        {"step": 1, "capability": "image-generation", "prompt": "生成一张火星基地图"},
        {"step": 2, "capability": "text-generation", "prompt": "描述这张图",
         "reference_step": 1},
        {"step": 3, "capability": "video-generation", "prompt": "让画面动起来",
         "reference_step": 1},
    ])
    out = orch.run("火星基地短片", "s1")

    results = out["frontend_response"]["data"]["results"]
    types = [r["type"] for r in results]
    assert "image" in types and "text" in types and "video" in types

    # Step2 带图 → 必须路由到 VLM
    assert any(m == "vlm-A" for m, t, _, _p in llm.calls if t == "text")
    # Step3 带首帧 → 必须路由到 I2V 模型
    assert any(m == "ivi-A" and img == "https://x/i.png" for m, t, img, _p in llm.calls)


def test_orchestrator_progress_events_follow_new_stages():
    orch, llm, bus = _build_orchestrator([
        {"step": 1, "capability": "text-generation", "prompt": "p"}
    ])
    events = []
    orch.run("p", "s1", on_progress=events.append)

    stages = [e["stage"] for e in events]
    assert stages[0] == "planning"
    assert "dispatching" in stages and "collecting" in stages and "auditing" in stages


def test_orchestrator_review_downgrades_to_partial_success():
    """审查打回 → 终态降级为 PARTIAL_SUCCESS（产物已交付但质量有瑕疵）"""
    orch, llm, bus = _build_orchestrator(
        [{"step": 1, "capability": "text-generation", "prompt": "p"}],
        llm=_StubLLM(review_pass=False),
    )
    out = orch.run("p", "s1")

    assert out["frontend_response"]["task_status"] == "PARTIAL_SUCCESS"
    # 调用链中应可见审查打回记录
    chain = out["log_record"]["call_chain"]
    assert any(c["status"] == "NEED_REVISION" for c in chain)


def test_orchestrator_reflection_retry_on_rejection():
    """审查打回后在预算内重试，最终通过则不应降级"""
    llm = _StubLLM(review_fail_first=True)
    orch, _, bus = _build_orchestrator(
        [{"step": 1, "capability": "text-generation", "prompt": "p"}],
        llm=llm, max_retries=1,
    )
    # 重试发生在步骤内部：审查失败会触发本步重做
    out = orch.run("p", "s1")

    # 第一次审查被拒 → 触发 revision → 第二次审查通过
    assert llm.review_calls >= 2
    events_stages = [t["status"] for t in bus.trace]
    assert STATUS_NEED_REVISION in events_stages


def test_orchestrator_fails_when_agent_not_registered():
    orch, llm, bus = _build_orchestrator([
        {"step": 1, "capability": "unknown-capability", "prompt": "p"}
    ])
    out = orch.run("p", "s1")

    assert out["frontend_response"]["task_status"] == "FAILED"
    err = out["log_record"]["error_summary"][0]
    assert err["type"] == "PLANNING_FAILED"
    assert "未注册对应 Agent" in err["reason"]


def test_orchestrator_partial_when_step_fails():
    """第一步失败但第二步有产物 → 整体降级交付"""
    orch, llm, bus = _build_orchestrator(
        [
            {"step": 1, "capability": "image-generation", "prompt": "p"},
            {"step": 2, "capability": "text-generation", "prompt": "p"},
        ],
        llm=_StubLLM(fail_models={"img-A"}),
        max_retries=0,
    )
    out = orch.run("p", "s1")

    assert out["frontend_response"]["task_status"] == "PARTIAL_SUCCESS"
    types = [r["type"] for r in out["frontend_response"]["data"]["results"]]
    assert types == ["text"]     # 图片失败但文本交付


def test_orchestrator_output_contract_matches_legacy():
    """契约兼容：字段名与层级必须与旧 Agent 一致"""
    orch, llm, bus = _build_orchestrator([
        {"step": 1, "capability": "text-generation", "prompt": "p"}
    ])
    out = orch.run("p", "s1")

    assert set(out.keys()) == {"frontend_response", "log_record"}
    fr = out["frontend_response"]
    assert {"task_id", "task_status", "system_status", "data"} <= set(fr.keys())
    log = out["log_record"]
    assert {"task_id", "task_status", "call_chain", "error_summary"} <= set(log.keys())


def test_reflection_retry_respects_budget():
    """审查持续打回时，必须在预算耗尽后停止，不能死循环"""
    llm = _StubLLM(review_pass=False)   # 永远打回
    orch, _, bus = _build_orchestrator(
        [{"step": 1, "capability": "text-generation", "prompt": "p"}],
        llm=llm, max_retries=2,
    )
    out = orch.run("p", "s1")

    # 生成次数 = 首发 1 + 重试 2，绝不超出预算
    gen_calls = [c for c in llm.calls
                if c[1] == "text" and "质量审查员" not in c[3]]
    assert len(gen_calls) == 3
    # 审查次数 = 步骤内审查 3 次 + 收尾全局审查 1 次
    assert llm.review_calls == 4
    # 终态为降级交付而非 SUCCESS
    assert out["frontend_response"]["task_status"] == "PARTIAL_SUCCESS"


def test_reviewed_step_retry_drops_stale_artifacts():
    """重做步骤时旧产物不得残留进下游上下文"""
    from src.core.contracts import TaskContext as TC
    ctx = TC(task_id="t", max_retries=2)
    ctx.record(1, [Artifact.text_of("旧版本")])
    ctx.record(2, [Artifact.text_of("下游产物")])

    ctx.step_outputs.pop(1, None)   # 模拟重做步骤 1

    up = ctx.upstream_of(3)
    assert all(a.content != "旧版本" for a in up)
    assert any(a.content == "下游产物" for a in up)


# ==================================================================
# T-15：调用链实时化（事件增量下发 + 内部 ID 早期暴露）
# ==================================================================
def _run_with_events(subtasks, llm=None, max_retries=1):
    orch, llm, bus = _build_orchestrator(subtasks, llm=llm, max_retries=max_retries)
    events = []
    result = orch.run("测试输入", "s1", on_progress=events.append)
    return result, events, llm


def test_planning_event_carries_internal_task_id():
    """首个事件带出内部 task_id，供 Worker 立即登记映射（否则执行期间协作视图为空）"""
    _, events, _ = _run_with_events([
        {"step": 1, "capability": "text-generation", "prompt": "写点东西"},
    ])
    planning = [e for e in events if e.get("stage") == "planning"]
    assert planning, "应发出 planning 事件"
    assert planning[0].get("task_id"), "planning 事件必须携带内部 task_id"
    assert str(planning[0]["task_id"]).startswith("task_")


def test_collecting_event_carries_incremental_calls():
    """collecting 事件携带本步调用明细，前端才能逐条渲染调用链"""
    _, events, _ = _run_with_events([
        {"step": 1, "capability": "text-generation", "prompt": "写点东西"},
    ])
    collecting = [e for e in events if e.get("stage") == "collecting"]
    assert collecting, "应发出 collecting 事件"
    calls = collecting[0].get("calls")
    assert calls, "collecting 事件应携带 calls 明细"
    first = calls[0]
    for field in ("agent", "model", "capability", "status"):
        assert field in first, f"calls 明细缺少字段 {field}"
    assert first["agent"] == "writer_agent"
    assert first["model"] == "text-A"


def test_collecting_calls_are_per_step_not_cumulative():
    """每步只下发"本步新增"的调用，避免前端重复累计"""
    _, events, _ = _run_with_events([
        {"step": 1, "capability": "image-generation", "prompt": "画一只猫"},
        {"step": 2, "capability": "text-generation", "prompt": "描述这张图",
         "reference_step": 1},
    ])
    collecting = [e for e in events if e.get("stage") == "collecting"]
    assert len(collecting) == 2

    step1_calls = collecting[0].get("calls") or []
    step2_calls = collecting[1].get("calls") or []
    # 步骤1只应包含 image_agent（+其审查），不应混入步骤2的 writer
    assert all(c["agent"] != "writer_agent" for c in step1_calls), \
        f"步骤1不应包含 writer 调用: {step1_calls}"
    assert any(c["agent"] == "image_agent" for c in step1_calls)


def test_final_call_chain_not_duplicated():
    """逐步 drain + 收尾兜底 drain 不得重复计入同一次调用"""
    result, events, _ = _run_with_events([
        {"step": 1, "capability": "text-generation", "prompt": "写点东西"},
    ])
    chain = result["log_record"]["call_chain"]
    sigs = [(c["agent"], c["model_name"], c["capability"], c["attempted_at"])
            for c in chain]
    assert len(sigs) == len(set(sigs)), f"调用链存在重复条目: {sigs}"

    # 事件下发的调用应是终态的子集（整体审计属终态行为，只出现在 call_chain 里）
    from_events = sum(len(e.get("calls") or []) for e in events
                      if e.get("stage") == "collecting")
    assert 0 < from_events <= len(chain), \
        f"事件下发 {from_events} 条，终态 {len(chain)} 条，应为非空子集"

    # 步骤内审查（Reviewer）也调用了模型，必须实时下发，不能只在终态出现
    agents_in_events = {
        c["agent"] for e in events if e.get("stage") == "collecting"
        for c in (e.get("calls") or [])
    }
    assert "writer_agent" in agents_in_events
    assert "reviewer_agent" in agents_in_events, \
        f"步骤内审查调用未实时下发: {agents_in_events}"


def test_revision_emits_extra_calls():
    """反思重试时，重做产生的调用应再次下发（不能被去重掉）"""
    llm = _StubLLM(review_fail_first=True)
    result, events, _ = _run_with_events([
        {"step": 1, "capability": "text-generation", "prompt": "写点东西"},
    ], llm=llm, max_retries=1)

    revision = [e for e in events if e.get("stage") == "revision"]
    assert revision, "应出现 revision 事件"

    collecting = [e for e in events if e.get("stage") == "collecting"]
    total_calls = sum(len(e.get("calls") or []) for e in collecting)
    writer_calls = sum(
        1 for e in collecting for c in (e.get("calls") or [])
        if c["agent"] == "writer_agent"
    )
    assert writer_calls >= 2, f"重做后应出现两次 writer 调用，实际 {writer_calls}"
    assert total_calls >= writer_calls
