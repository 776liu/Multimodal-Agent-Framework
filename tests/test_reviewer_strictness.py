"""Reviewer 严格度分级测试（工单 T-04）

用假模型返回固定分数，验证**阈值真正生效**——这是本次修复的核心：
修复前判定采信模型自报的 `pass` 字段，本项目定义的阈值形同虚设；
修复后判定只依据评分阈值，严格度可配置、可预测、可回归验证。
"""
import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.agents.reviewer_agent import ReviewerAgent
from src.core.contracts import Artifact, AgentMessage, TaskContext
from src.core.models import LLMResponse, TaskResult


class FakeRouter:
    def get_model(self, capability, failed_models=None):
        return {"registered_name": "fake", "model_name": "fake",
                "endpoint": "http://fake", "api_key": "k",
                "capability": capability}


class FakeLLM:
    """返回预设的审查 JSON"""

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = 0

    def call(self, **kwargs):
        self.calls += 1
        return LLMResponse(
            status="SUCCESS",
            data=TaskResult(type="text", content=json.dumps(self.payload,
                                                            ensure_ascii=False)),
            model_name="fake",
        )


def _review(payload: dict, **kwargs):
    """跑一次审查，返回 AgentResponse"""
    llm = FakeLLM(payload)
    reviewer = ReviewerAgent(FakeRouter(), llm, **kwargs)
    art = Artifact.text_of("这是一段足够长的待审查文本内容，用于触发深度评估流程。", step=1)
    msg = AgentMessage(task_id="t", step=1, sender="o",
                       receiver=reviewer.name, prompt="审查", artifacts=[art])
    ctx = TaskContext(task_id="t", session_id="s", user_input="")
    return reviewer.execute(msg, ctx)


# ----------------------------------------------------------------------
# 核心：阈值真正生效（修复前会被模型的 pass 字段绕过）
# ----------------------------------------------------------------------
def test_score_above_threshold_passes():
    r = _review({"score": 5, "issues": []})
    assert r.status == "SUCCESS"
    assert "审查通过" in r.output_text


def test_score_at_pass_threshold_passes():
    r = _review({"score": 4, "issues": []}, pass_threshold=4)
    assert r.status == "SUCCESS"


def test_score_in_warn_band_passes_with_warning():
    """3~4 分：放行交付但记录警告，不触发反思重试（省 Token）"""
    r = _review({"score": 3, "issues": ["表述略笼统"]},
                pass_threshold=4, warn_threshold=3)
    assert r.status == "SUCCESS", "落入警告带应放行而非打回"
    assert "警告" in r.output_text
    assert "表述略笼统" in r.output_text


def test_score_below_warn_threshold_rejects():
    r = _review({"score": 2, "issues": ["存在事实错误"]},
                pass_threshold=4, warn_threshold=3)
    assert r.status == "NEED_REVISION"
    assert any("低于交付标准" in i for i in r.issues)


def test_model_pass_field_no_longer_overrides_threshold():
    """**核心回归**：模型自报 pass=false 但评分达标时，仍应通过。

    修复前 `passed = data.get("pass", score >= 3)` 会采信 pass=false 而打回，
    导致本项目阈值失效。
    """
    r = _review({"score": 5, "issues": [], "pass": False},
                pass_threshold=4, warn_threshold=3)
    assert r.status == "SUCCESS", "评分达标时不得被模型自报的 pass 字段否决"


def test_model_pass_true_no_longer_bypasses_threshold():
    """反向：模型自报 pass=true 但评分过低时，必须打回"""
    r = _review({"score": 1, "issues": ["严重错误"], "pass": True},
                pass_threshold=4, warn_threshold=3)
    assert r.status == "NEED_REVISION", "评分过低时不得被模型自报的 pass=true 放行"


# ----------------------------------------------------------------------
# 严格度可配置：同一分数在不同阈值下结果不同
# ----------------------------------------------------------------------
def test_threshold_is_configurable():
    payload = {"score": 4, "issues": []}

    strict = _review(payload, pass_threshold=5, warn_threshold=4)
    assert strict.status == "SUCCESS"
    assert "警告" in strict.output_text, "严格阈值下 4 分应落入警告带"

    loose = _review(payload, pass_threshold=3, warn_threshold=2)
    assert loose.status == "SUCCESS"
    assert "警告" not in loose.output_text, "宽松阈值下 4 分应直接通过"


# ----------------------------------------------------------------------
# 异常容错：解析失败不应误伤产物
# ----------------------------------------------------------------------
def test_missing_score_falls_back_to_pass():
    """缺少 score 字段 → 视为解析异常 → 保守放行"""
    llm = FakeLLM({})
    reviewer = ReviewerAgent(FakeRouter(), llm)
    art = Artifact.text_of("这是一段足够长的待审查文本内容，用于触发深度评估流程。", step=1)
    msg = AgentMessage(task_id="t", step=1, sender="o",
                       receiver=reviewer.name, prompt="审查", artifacts=[art])
    r = reviewer.execute(msg, TaskContext(task_id="t", session_id="s", user_input=""))
    assert r.status == "SUCCESS"
    assert "解析失败" in r.output_text


def test_out_of_range_score_falls_back_to_pass():
    r = _review({"score": 99, "issues": []})
    assert r.status == "SUCCESS"
    assert "解析失败" in r.output_text


def test_parse_verdict_returns_pair():
    """解析接口返回 (score, issues)，不再含 pass"""
    parsed = ReviewerAgent._parse_verdict('{"score": 4, "issues": ["a"]}')
    assert parsed == (4, ["a"])


def test_parse_verdict_handles_markdown_fence():
    parsed = ReviewerAgent._parse_verdict('```json\n{"score": 5, "issues": []}\n```')
    assert parsed == (5, [])


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
