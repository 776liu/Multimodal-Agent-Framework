"""双车道队列测试（工单 T-05）

覆盖：车道预判 / 双队列隔离 / 消费侧纠偏改派 / 内存实现接口一致性。
Redis 用例在 Redis 不可用时自动跳过。
"""
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.api.redis_task_manager import guess_lane, LANE_FAST, LANE_SLOW, QUEUE_KEYS
from src.api.task_manager import MemoryTaskManager


# ----------------------------------------------------------------------
# 车道预判（纯函数，无外部依赖）
# ----------------------------------------------------------------------
def test_guess_lane_video_keywords():
    """含视频类关键词 → 慢车道"""
    cases = [
        "生成一段5秒的视频：城市夜晚的霓虹街道",
        "帮我做一个短片，讲城市变迁",
        "生成一个动画分镜",
        "做一个 MV",
        "make a video of a running dog",
    ]
    for text in cases:
        assert guess_lane(text) == LANE_SLOW, f"「{text}」应为慢车道"


def test_guess_lane_text_and_image():
    """文本/图片任务 → 快车道"""
    cases = [
        "把 Hello World 翻译成中文",
        "生成一张赛博朋克风格的图片",
        "写一段关于春天的文案",
        "",
    ]
    for text in cases:
        assert guess_lane(text) == LANE_FAST, f"「{text}」应为快车道"


def test_queue_keys_distinct():
    """两车道物理队列不同名，避免互相消费"""
    assert QUEUE_KEYS[LANE_FAST] != QUEUE_KEYS[LANE_SLOW]


# ----------------------------------------------------------------------
# 内存实现：接口一致性 + 分车道语义
# ----------------------------------------------------------------------
def test_memory_lane_isolation():
    """快慢车道各自只能取到本车道任务"""
    tm = MemoryTaskManager()
    fast_task = tm.create_task("翻译一段文字", "s1", lane=LANE_FAST)["task_id"]
    slow_task = tm.create_task("生成视频", "s1", lane=LANE_SLOW)["task_id"]

    got = tm.dequeue(timeout=0, lane=LANE_FAST)
    assert got is not None and got[0] == fast_task, "快车道应取到文本任务"

    got = tm.dequeue(timeout=0, lane=LANE_SLOW)
    assert got is not None and got[0] == slow_task, "慢车道应取到视频任务"


def test_memory_requeue_to_lane():
    """改派后任务状态回到 pending 且落到目标车道"""
    tm = MemoryTaskManager()
    task_id = tm.create_task("生成视频", "s1", lane=LANE_FAST)["task_id"]
    tm.update_task(task_id, "processing")

    tm.requeue_to_lane(task_id, LANE_SLOW)

    assert tm.get_task(task_id)["status"] == "pending"
    got = tm.dequeue(timeout=0, lane=LANE_FAST)
    assert got is None, "改派后快车道不应再取到该任务"
    got = tm.dequeue(timeout=0, lane=LANE_SLOW)
    assert got is not None and got[0] == task_id


def test_memory_dequeue_without_lane_backward_compatible():
    """不传 lane 时行为与旧版一致（不限车道）"""
    tm = MemoryTaskManager()
    tid = tm.create_task("任意任务", "s1", lane=LANE_SLOW)["task_id"]
    got = tm.dequeue(timeout=0)
    assert got is not None and got[0] == tid


# ----------------------------------------------------------------------
# Redis 实现（需要真实 Redis，不可用则跳过）
# ----------------------------------------------------------------------
def _redis_available() -> bool:
    try:
        import redis
        client = redis.Redis(host="localhost", port=6379, decode_responses=True,
                             socket_connect_timeout=1)
        return client.ping()
    except Exception:
        return False


# 测试用独立队列名，避免与正在运行的服务端 Worker 抢占同一队列
# （否则 Worker 会立刻消费掉测试塞进去的任务，造成偶发失败）
_TEST_QUEUES = {
    LANE_FAST: "agent:queue:test:fast",
    LANE_SLOW: "agent:queue:test:slow",
}


def _make_tm():
    from src.api.redis_task_manager import RedisTaskManager
    return RedisTaskManager(expire_seconds=30, queue_keys=_TEST_QUEUES)


def test_redis_dual_lane_roundtrip():
    """Redis 版：两车道独立入队/出队，且互不串道"""
    if not _redis_available():
        print("  (Redis 不可用，跳过)")
        return

    tm = _make_tm()
    tm.client.delete(_TEST_QUEUES[LANE_FAST], _TEST_QUEUES[LANE_SLOW])

    fast_id = tm.create_task("翻译一段文字", "lane-test", lane=LANE_FAST)["task_id"]
    slow_id = tm.create_task("生成一段视频", "lane-test", lane=LANE_SLOW)["task_id"]

    assert tm.get_task(fast_id)["lane"] == LANE_FAST
    assert tm.get_task(slow_id)["lane"] == LANE_SLOW

    got = tm.dequeue(timeout=1, lane=LANE_SLOW)
    assert got is not None and got[0] == slow_id, "慢车道应先取到自己那个任务"

    got = tm.dequeue(timeout=1, lane=LANE_FAST)
    assert got is not None and got[0] == fast_id


def test_redis_requeue_to_lane():
    """Redis 版：改派后任务落到目标车道并重置为 pending"""
    if not _redis_available():
        print("  (Redis 不可用，跳过)")
        return

    tm = _make_tm()
    tm.client.delete(_TEST_QUEUES[LANE_FAST], _TEST_QUEUES[LANE_SLOW])

    tid = tm.create_task("生成视频", "lane-test", lane=LANE_FAST)["task_id"]
    tm.dequeue(timeout=1, lane=LANE_FAST)          # 被快车道捡走
    tm.update_task(tid, "processing")
    tm.requeue_to_lane(tid, LANE_SLOW)

    info = tm.get_task(tid)
    assert info["status"] == "pending"
    assert info["lane"] == LANE_SLOW

    got = tm.dequeue(timeout=1, lane=LANE_SLOW)
    assert got is not None and got[0] == tid
    assert tm.dequeue(timeout=0, lane=LANE_FAST) is None


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
