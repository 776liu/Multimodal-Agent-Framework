"""多轮对话规划上下文测试

覆盖：结构化标记 / 当前指令去重 / 产物回填 / 单轮退化 / Prompt 铁律存在性。
对应缺陷：多轮会话中 TaskRouter 会把历史里已完成的任务重复排入执行计划。
"""
import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.memory import Memory
from src.core.task_router import SYSTEM_PROMPT


# ----------------------------------------------------------------------
# build_context 结构化输出
# ----------------------------------------------------------------------
def test_no_history_returns_raw_input():
    """单轮（无历史）直接返回原文，不加标记"""
    mem = Memory()
    mem.add("s1", "user", "把 Hello World 翻译成中文")
    # 调用约定：先 add 当前输入再 build
    out = mem.build_context("s1", "把 Hello World 翻译成中文")
    assert out == "把 Hello World 翻译成中文"
    assert "<history>" not in out


def test_current_input_not_duplicated():
    """当前指令只出现在 <current_request> 中，不在 <history> 里重复"""
    mem = Memory()
    mem.add("s1", "user", "把 Hello World 翻译成中文")
    mem.add("s1", "assistant", json.dumps(
        {"results": [{"type": "text", "content": "你好，世界"}]}, ensure_ascii=False))
    mem.add("s1", "user", "生成一段5秒的视频：城市夜晚的霓虹街道")

    out = mem.build_context("s1", "生成一段5秒的视频：城市夜晚的霓虹街道")

    assert out.count("生成一段5秒的视频") == 1, "当前指令不应重复出现"
    assert "<current_request>生成一段5秒的视频：城市夜晚的霓虹街道</current_request>" in out
    # 历史里应保留上一轮，但不含当前指令
    assert "<history>" in out
    history_part = out.split("</history>")[0]
    assert "把 Hello World 翻译成中文" in history_part
    assert "生成一段5秒的视频" not in history_part


def test_history_contains_previous_artifacts():
    """历史中回填图片与视频产物，供模型理解指代"""
    mem = Memory()
    mem.add("s1", "user", "生成一张赛博朋克城市图")
    mem.add("s1", "assistant", json.dumps(
        {"results": [{"type": "image", "url": "https://example.com/a.png"}]},
        ensure_ascii=False))
    mem.add("s1", "user", "给这个画面配文案")

    out = mem.build_context("s1", "给这个画面配文案")
    assert "https://example.com/a.png" in out


def test_video_artifact_backfilled():
    """视频产物也应回填（此前只处理 text/image）"""
    mem = Memory()
    mem.add("s1", "user", "生成一段视频")
    mem.add("s1", "assistant", json.dumps(
        {"results": [{"type": "video", "url": "https://example.com/v.mp4"}]},
        ensure_ascii=False))
    mem.add("s1", "user", "给这段视频配旁白")

    out = mem.build_context("s1", "给这段视频配旁白")
    assert "https://example.com/v.mp4" in out
    assert "视频" in out


def test_current_input_only_after_pure_history():
    """历史非空但全是助手消息时，当前指令仍完整给出"""
    mem = Memory()
    mem.add("s1", "assistant", "上一步生成了文本：你好")
    mem.add("s1", "user", "再来一段")
    out = mem.build_context("s1", "再来一段")
    assert "<current_request>再来一段</current_request>" in out


# ----------------------------------------------------------------------
# SYSTEM_PROMPT 约束
# ----------------------------------------------------------------------
def test_prompt_has_multiturn_rules():
    """Prompt 必须含多轮铁律与结构化标记说明"""
    assert "<history>" in SYSTEM_PROMPT
    assert "<current_request>" in SYSTEM_PROMPT
    assert "禁止重复执行" in SYSTEM_PROMPT
    assert "只拆解 <current_request>" in SYSTEM_PROMPT


def test_prompt_has_multiturn_example():
    """Prompt 必须含"历史已完成、只拆当前"的 few-shot 示例"""
    idx = SYSTEM_PROMPT.find("多轮示例")
    assert idx != -1, "缺少多轮 few-shot 示例"
    tail = SYSTEM_PROMPT[idx:]
    assert "不得重复排入计划" in tail


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
    print(f"\n结果: {len(tests) - failed} 通过 / {failed} 失败")
    sys.exit(1 if failed else 0)
