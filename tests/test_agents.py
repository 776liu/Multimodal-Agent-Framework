"""多 Agent 阶段二（专业 Agent）单元测试

覆盖:
- WriterAgent: 纯文本路由 / 带图自动切 VLM / 空内容处理 / 模型降级
- ImageAgent: 文生图 / 图生图 / URL 缺失处理 / 模型降级
- ReviewerAgent: 规则快筛拦截 / LLM 打回 / JSON 容错解析 / 审查模型不可用降级
- 三者协作: MessageBus 串联 Writer → Reviewer 的产物流转与打回
"""
import json

import pytest

from src.core.agents import WriterAgent, ImageAgent, ReviewerAgent
from src.core.contracts import (
    Artifact,
    AgentMessage,
    AgentResponse,
    TaskContext,
    STATUS_SUCCESS,
    STATUS_NEED_REVISION,
    ARTIFACT_TEXT,
    ARTIFACT_IMAGE,
)
from src.core.message_bus import MessageBus
from src.core.models import ModelInfo
from src.core.router import Router


# ==================================================================
# 测试替身
# ==================================================================
class _StubLLM:
    """按 (model_name, output_type) 编排返回，便于覆盖各种分支"""

    def __init__(self, text="一段足够长的文本内容用于测试审查规则", image_url="https://x/i.png",
                 vision_text=None, review_json=None, fail_models=(), fail_review=False):
        self.text = text
        self.image_url = image_url
        self.vision_text = vision_text
        self.review_json = review_json
        self.fail_models = set(fail_models)
        self.fail_review = fail_review
        self.calls = []

    def call(self, model_name, endpoint, api_key, prompt, output_type, image_url=""):
        self.calls.append({"model": model_name, "type": output_type, "image": image_url})

        if model_name in self.fail_models:
            return _resp_fail(503)
        if self.fail_review:
            return _resp_fail(503)

        if output_type == "image":
            return _resp_ok_image(self.image_url)
        if output_type == "text":
            if "质量审查员" in prompt or "审查" in prompt:
                # 审查调用
                body = self.review_json or '{"score": 5, "issues": [], "pass": true}'
                return _resp_ok_text(body)
            if image_url and self.vision_text is not None:
                return _resp_ok_text(self.vision_text)
            return _resp_ok_text(self.text)
        return _resp_fail(-1)


class _Resp:
    def __init__(self, status, data=None, error_code=None):
        self.status = status
        self.data = data
        self.error_code = error_code


class _Data:
    def __init__(self, content=None, url=None, type="text"):
        self.content = content
        self.url = url
        self.type = type


def _resp_ok_text(c):
    return _Resp("SUCCESS", _Data(content=c, type="text"))


def _resp_ok_image(u):
    return _Resp("SUCCESS", _Data(url=u, type="image"))


def _resp_fail(code):
    return _Resp("FAILED", None, code)


def _router():
    """文本池 + 视觉池 + 图片池"""
    return Router([
        ModelInfo("writer-primary", "text-A", "e", "k", "text-generation"),
        ModelInfo("writer-backup", "text-B", "e", "k", "text-generation"),
        ModelInfo("vlm-primary", "vlm-A", "e", "k", "image-to-text"),
        ModelInfo("img-primary", "img-A", "e", "k", "image-generation"),
        ModelInfo("img-backup", "img-B", "e", "k", "image-generation"),
    ])


def _msg(receiver="writer_agent", prompt="写一段文案", artifacts=None, step=1, capability="text-generation"):
    return AgentMessage(
        task_id="t1", step=step, sender="orchestrator", receiver=receiver,
        prompt=prompt, capability=capability, artifacts=artifacts or [],
    )


# ==================================================================
# WriterAgent
# ==================================================================
def test_writer_agent_plain_text():
    llm = _StubLLM(text="这是一段足够长的中文文案内容。")
    agent = WriterAgent(_router(), llm)
    ctx = TaskContext(task_id="t1")

    resp = agent.execute(_msg(), ctx)

    assert resp.ok
    assert resp.artifacts[0].type == ARTIFACT_TEXT
    assert resp.artifacts[0].content == "这是一段足够长的中文文案内容。"
    assert llm.calls[0]["model"] == "text-A"


def test_writer_agent_routes_to_vlm_when_image_present():
    """带图输入必须切到 image-to-text 池，否则纯文本模型会返回 20041"""
    llm = _StubLLM(vision_text="这是一张赛博朋克风格的城市夜景图。")
    agent = WriterAgent(_router(), llm)
    ctx = TaskContext(task_id="t1")

    msg = _msg(prompt="描述这张图片",
               artifacts=[Artifact.image_of("https://x/img.png")])
    resp = agent.execute(msg, ctx)

    assert resp.ok
    assert llm.calls[0]["model"] == "vlm-A"      # 走了 VLM
    assert llm.calls[0]["image"] == "https://x/img.png"
    assert resp.artifacts[0].metadata["used_vision"] is True
    # 只回传本次新产物，上游图片不得重复回传（否则结果集中出现重复图片）
    assert len(resp.artifacts) == 1
    assert resp.artifacts[0].type == ARTIFACT_TEXT


def test_writer_agent_rejects_empty_content():
    llm = _StubLLM(text="   ")
    agent = WriterAgent(_router(), llm)
    resp = agent.execute(_msg(), TaskContext(task_id="t1"))
    assert resp.ok is False
    assert "空内容" in resp.issues[0]


def test_writer_agent_falls_back_on_model_failure():
    llm = _StubLLM(fail_models={"text-A"})
    agent = WriterAgent(_router(), llm)
    resp = agent.execute(_msg(), TaskContext(task_id="t1", max_retries=2))

    assert resp.ok
    assert [c["model"] for c in llm.calls] == ["text-A", "text-B"]


# ==================================================================
# ImageAgent
# ==================================================================
def test_image_agent_text_to_image():
    llm = _StubLLM(image_url="https://x/generated.png")
    agent = ImageAgent(_router(), llm)

    resp = agent.execute(
        _msg(receiver="image_agent", prompt="一只柴犬", capability="image-generation"),
        TaskContext(task_id="t1"),
    )

    assert resp.ok
    assert resp.artifacts[0].type == ARTIFACT_IMAGE
    assert resp.artifacts[0].content == "https://x/generated.png"
    assert resp.artifacts[0].metadata["mode"] == "text-to-image"


def test_image_agent_image_to_image_passes_reference():
    llm = _StubLLM(image_url="https://x/out.png")
    agent = ImageAgent(_router(), llm)

    resp = agent.execute(
        _msg(receiver="image_agent", prompt="让它动起来",
             artifacts=[Artifact.image_of("https://x/ref.png")],
             capability="image-generation"),
        TaskContext(task_id="t1"),
    )

    assert resp.ok
    assert llm.calls[0]["image"] == "https://x/ref.png"   # 参考图透传
    assert resp.artifacts[0].metadata["mode"] == "image-to-image"


def test_image_agent_rejects_missing_url():
    llm = _StubLLM(image_url=None)
    agent = ImageAgent(_router(), llm)
    resp = agent.execute(
        _msg(receiver="image_agent", capability="image-generation"),
        TaskContext(task_id="t1", max_retries=0),
    )
    assert resp.ok is False


def test_image_agent_falls_back_to_backup():
    llm = _StubLLM(fail_models={"img-A"})
    agent = ImageAgent(_router(), llm)
    resp = agent.execute(
        _msg(receiver="image_agent", capability="image-generation"),
        TaskContext(task_id="t1", max_retries=2),
    )
    assert resp.ok
    assert [c["model"] for c in llm.calls] == ["img-A", "img-B"]


# ==================================================================
# ReviewerAgent
# ==================================================================
def test_reviewer_rule_check_blocks_empty_artifact():
    agent = ReviewerAgent(_router(), _StubLLM(), enable_llm_review=False)
    resp = agent.execute(
        _msg(receiver="reviewer_agent", artifacts=[Artifact.text_of("  ")]),
        TaskContext(task_id="t1", max_retries=0),
    )
    assert resp.status == STATUS_NEED_REVISION
    assert "内容为空" in resp.issues[0]


def test_reviewer_rule_check_blocks_short_text():
    agent = ReviewerAgent(_router(), _StubLLM(), enable_llm_review=False)
    resp = agent.execute(
        _msg(receiver="reviewer_agent", artifacts=[Artifact.text_of("太短")]),
        TaskContext(task_id="t1", max_retries=0),
    )
    assert resp.status == STATUS_NEED_REVISION
    assert "文本内容过短" in resp.issues[0]


def test_reviewer_rule_check_blocks_bad_url():
    agent = ReviewerAgent(_router(), _StubLLM(), enable_llm_review=False)
    resp = agent.execute(
        _msg(receiver="reviewer_agent", artifacts=[Artifact.image_of("not-a-url")]),
        TaskContext(task_id="t1", max_retries=0),
    )
    assert resp.status == STATUS_NEED_REVISION
    assert "URL格式异常" in resp.issues[0]


def test_reviewer_llm_rejects_with_issues():
    """LLM 判定不通过时返回 NEED_REVISION 并携带修改建议"""
    review = json.dumps({"score": 2, "issues": ["事实错误：把企鹅说成北极熊"], "pass": False},
                       ensure_ascii=False)
    agent = ReviewerAgent(_router(), _StubLLM(review_json=review))
    resp = agent.execute(
        _msg(receiver="reviewer_agent",
             artifacts=[Artifact.text_of("这是一段足够长的正常文本内容。")]),
        TaskContext(task_id="t1", max_retries=0),
    )
    assert resp.status == STATUS_NEED_REVISION
    assert any("事实错误" in i for i in resp.issues)
    assert any("2/5" in i for i in resp.issues)


def test_reviewer_llm_passes():
    agent = ReviewerAgent(_router(), _StubLLM(review_json='{"score": 5, "issues": [], "pass": true}'))
    resp = agent.execute(
        _msg(receiver="reviewer_agent",
             artifacts=[Artifact.text_of("这是一段足够长且质量优秀的文本内容。")]),
        TaskContext(task_id="t1", max_retries=0),
    )
    assert resp.ok
    assert "5/5" in resp.output_text


def test_reviewer_tolerates_markdown_wrapped_json():
    """审查模型常用 ```json 包裹，需容错解析"""
    review = '```json\n{"score": 4, "issues": ["小瑕疵"], "pass": true}\n```'
    agent = ReviewerAgent(_router(), _StubLLM(review_json=review))
    resp = agent.execute(
        _msg(receiver="reviewer_agent",
             artifacts=[Artifact.text_of("这是一段足够长且质量优秀的文本内容。")]),
        TaskContext(task_id="t1", max_retries=0),
    )
    assert resp.ok


def test_reviewer_degrades_when_review_model_unavailable():
    """审查模型不可用不应阻断主流程，降级放行"""
    agent = ReviewerAgent(_router(), _StubLLM(fail_review=True))
    resp = agent.execute(
        _msg(receiver="reviewer_agent",
             artifacts=[Artifact.text_of("这是一段足够长且质量优秀的文本内容。")]),
        TaskContext(task_id="t1", max_retries=0),
    )
    assert resp.ok
    assert "降级" in resp.output_text


def test_reviewer_rejects_when_no_artifacts():
    agent = ReviewerAgent(_router(), _StubLLM())
    resp = agent.execute(
        _msg(receiver="reviewer_agent", artifacts=[]),
        TaskContext(task_id="t1", max_retries=0),
    )
    assert resp.ok is False


# ==================================================================
# 协作：Writer → Reviewer 的完整闭环
# ==================================================================
def test_writer_then_reviewer_flow():
    """Writer 产出被 Reviewer 审查，产物链路完整"""
    bus = MessageBus()
    bus.register(WriterAgent(_router(), _StubLLM(text="火星探险日记正文，描述了红色星球的荒漠与穹顶基地。")))
    bus.register(ReviewerAgent(_router(), _StubLLM()))

    ctx = TaskContext(task_id="t1", session_id="s1")

    r1 = bus.dispatch(_msg(prompt="写一段火星探险日记"), ctx)
    assert r1.ok

    # Orchestrator 把上游产物交给 Reviewer
    review_msg = _msg(receiver="reviewer_agent", prompt="审查这段文案",
                      artifacts=bus.collect_artifacts([r1]), step=2)
    r2 = bus.dispatch(review_msg, ctx)

    assert r2.ok
    assert review_msg.artifacts[0].content.startswith("火星探险日记")


def test_reviewer_rejection_triggers_retry_within_budget():
    """审查打回 → Orchestrator 可在同一预算内触发重试"""
    writer = WriterAgent(_router(), _StubLLM(text="太短"))
    reviewer = ReviewerAgent(_router(), _StubLLM(), enable_llm_review=False)
    bus = MessageBus()
    bus.register(writer)
    bus.register(reviewer)

    ctx = TaskContext(task_id="t1", max_retries=2)

    r1 = bus.dispatch(_msg(prompt="写文案", step=1), ctx)
    ctx.record(1, r1.artifacts)

    review_msg = _msg(receiver="reviewer_agent", prompt="审查",
                      artifacts=ctx.upstream_of(2), step=2)
    r2 = bus.dispatch(review_msg, ctx)

    assert r2.status == STATUS_NEED_REVISION
    # 预算充足，Orchestrator 可以要求重做
    assert ctx.can_retry(1) is True
    ctx.bump(1)
    assert ctx.can_retry(1) is True


# ==================================================================
# NEED_REVISION 语义：终态而非模型故障（回归防护）
# ==================================================================
def test_need_revision_is_terminal_not_retried():
    """审查打回是内容质量问题，换模型重试无意义，应立即返回且只调用一次模型"""
    calls = {"n": 0}

    class _CountingLLM(_StubLLM):
        def call(self, model_name, endpoint, api_key, prompt, output_type, image_url=""):
            calls["n"] += 1
            return _resp_ok_text('{"score": 1, "issues": ["事实错误"], "pass": false}')

    agent = ReviewerAgent(_router(), _CountingLLM())
    ctx = TaskContext(task_id="t1", max_retries=2)
    msg = _msg(receiver="reviewer_agent",
               artifacts=[Artifact.text_of("这是一段足够长但内容有严重问题的文本。")])

    resp = agent.execute(msg, ctx)

    assert resp.status == STATUS_NEED_REVISION
    assert calls["n"] == 1, "打回后不应再换模型重试"
    chain = agent.drain_call_chain()
    assert [c.status for c in chain] == ["NEED_REVISION"]


def test_rule_check_short_circuit_costs_no_model_call():
    """规则快筛命中时应零模型调用"""
    calls = {"n": 0}

    class _NeverCalled(_StubLLM):
        def call(self, *a, **kw):
            calls["n"] += 1
            return super().call(*a, **kw)

    agent = ReviewerAgent(_router(), _NeverCalled())
    resp = agent.execute(
        _msg(receiver="reviewer_agent", artifacts=[Artifact.text_of("短")]),
        TaskContext(task_id="t1", max_retries=2),
    )

    assert resp.status == STATUS_NEED_REVISION
    assert calls["n"] == 0, "规则快筛拦截时不应调用任何模型"


def test_reviewer_skips_llm_review_for_media_only():
    """纯媒体产物不做 LLM 深度评估：纯文本模型无法核验视频/图片，
    强行评估会误判并白白触发反思重试（如重跑一次 5 分钟的视频生成）"""
    calls = {"n": 0}

    class _CountLLM(_StubLLM):
        def call(self, model_name, endpoint, api_key, prompt, output_type, image_url=""):
            calls["n"] += 1
            return super().call(model_name, endpoint, api_key, prompt, output_type, image_url)

    agent = ReviewerAgent(_router(), _CountLLM())
    resp = agent.execute(
        _msg(receiver="reviewer_agent",
             artifacts=[Artifact.video_of("https://x/v.mp4")]),
        TaskContext(task_id="t1", max_retries=2),
    )

    assert resp.ok
    assert calls["n"] == 0, "媒体产物不应触发任何模型调用"
    assert "规则核验" in resp.output_text


def test_reviewer_reviews_text_among_media():
    """文本 + 视频混合时，只对文本做深度评估，媒体走规则"""
    agent = ReviewerAgent(_router(), _StubLLM())
    resp = agent.execute(
        _msg(receiver="reviewer_agent", artifacts=[
            Artifact.text_of("这是一段足够长的正文内容。"),
            Artifact.video_of("https://x/v.mp4"),
        ]),
        TaskContext(task_id="t1", max_retries=0),
    )
    assert resp.ok
    assert "评分" in resp.output_text


def test_call_chain_omits_short_circuit_reviews():
    """规则层短路未调模型时，调用链不得出现虚假模型记录"""
    agent = ReviewerAgent(_router(), _StubLLM())
    resp = agent.execute(
        _msg(receiver="reviewer_agent", artifacts=[Artifact.video_of("https://x/v.mp4")]),
        TaskContext(task_id="t1", max_retries=0),
    )
    assert resp.ok
    assert agent.drain_call_chain() == [], "未调用模型则不应有链路记录"


def test_call_chain_records_real_model_calls():
    """真实调用模型的步骤必须留下链路记录"""
    agent = ReviewerAgent(_router(), _StubLLM())
    resp = agent.execute(
        _msg(receiver="reviewer_agent", artifacts=[Artifact.text_of("这是一段足够长的正文内容。")]),
        TaskContext(task_id="t1", max_retries=0),
    )
    assert resp.ok
    chain = agent.drain_call_chain()
    assert len(chain) == 1 and chain[0].model_name == "text-A"
