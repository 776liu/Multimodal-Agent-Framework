"""生成层提示词辅助测试

覆盖：文字诉求识别 / 否定表达消歧 / 幂等性 / 图像与视频约束文案区分。
"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.prompt_policy import (
    apply_no_text,
    has_explicit_no_text,
    has_text_intent,
)


def test_appends_constraint_for_plain_prompt():
    """普通描述会被追加无文字约束"""
    out = apply_no_text("一只柴犬在夕阳下奔跑")
    assert "禁止出现任何文字" in out
    assert out.startswith("一只柴犬在夕阳下奔跑")


def test_respects_explicit_text_intent():
    """用户明确要画面文字时不追加，避免指令冲突"""
    cases = [
        "生成一张带'欢迎光临'标语的招牌照片",
        "做一个咖啡店海报，上面写 LATTE",
        "设计一张有中文标题的宣传图",
        "create a poster with the word SALE",
        "做一个带 logo 的品牌图",
    ]
    for prompt in cases:
        assert apply_no_text(prompt) == prompt, f"「{prompt}」不应追加"


def test_respects_explicit_negation():
    """用户自己写了无文字约束时不重复追加"""
    for prompt in ("生成一张赛博朋克城市图，不要文字",
                   "一只猫，纯画面无水印"):
        assert apply_no_text(prompt) == prompt, f"「{prompt}」不应重复追加"


def test_idempotent():
    """重复调用不重复追加"""
    once = apply_no_text("一只狐狸")
    twice = apply_no_text(once)
    assert once == twice


def test_video_constraint_differs():
    """视频使用视频专用约束文案"""
    img = apply_no_text("镜头推进", is_video=False)
    vid = apply_no_text("镜头推进", is_video=True)
    assert "全片段需保持画面干净无文字" in vid
    assert "全片段需保持画面干净无文字" not in img


def test_empty_prompt():
    assert apply_no_text("") == ""


def test_intent_helpers():
    assert has_text_intent("带字幕的视频")
    assert has_text_intent("with typography")
    assert not has_text_intent("雨夜的街道")
    assert has_explicit_no_text("不要文字")
    assert not has_explicit_no_text("一只猫")


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
