import uuid
import json
import time
import redis
from src.api.task_manager import TaskManager

# 快慢车道队列名（工单 T-05）
LANE_FAST = "fast"   # 文本/图片等秒级任务
LANE_SLOW = "slow"   # 视频等分钟级长任务

#: 各车道对应的物理队列 key
QUEUE_KEYS = {
    LANE_FAST: "agent:queue",
    LANE_SLOW: "agent:queue:slow",
}


def guess_lane(user_input: str) -> str:
    """提交时按关键词预判车道。

    TaskRouter 未执行前无法准确知道任务类型（那是 PLANNING 的职责），
    这里用轻量规则做第一道分流：命中视频类关键词即进慢车道。
    预判失误由 Worker 侧 requeue_to_lane 二次纠正（双保险）。
    """
    if not user_input:
        return LANE_FAST
    lowered = user_input.lower()
    video_keywords = (
        "视频", "短片", "动画", "mv", "MV", "影片", " footage",
        "一段5秒", "一段十秒", "生成视频", "做视频", "video", "clip",
    )
    return LANE_SLOW if any(k in lowered for k in video_keywords) else LANE_FAST


class RedisTaskManager(TaskManager):
    """任务管理器:List 做队列,Hash 做状态存储

    双车道（工单 T-05）：
        fast  -> agent:queue       （文本/图片等秒级任务）
        slow  -> agent:queue:slow  （视频等分钟级长任务）
    目的：视频长任务不再阻塞文本任务的消费（毕设差异点 1 / E2 实验）。
    """
    def __init__(self,
                 host: str = "localhost",
                 port: int = 6379,
                 queue_key: str = "agent:queue",
                 expire_seconds: int = 3600,
                 task_prefix: str = "agent:task:",
                 progress_prefix: str = "agent:progress:",
                 id_map_prefix: str = "agent:idmap:",
                 queue_keys: dict = None):
        pool = redis.ConnectionPool(host=host, port=port, decode_responses=True)
        self.client = redis.Redis(connection_pool=pool)
        self.queue_key = queue_key
        self.expire_seconds = expire_seconds
        self._task_prefix = task_prefix
        self._progress_prefix = progress_prefix
        self._id_map_prefix = id_map_prefix
        # 车道→队列名映射，可注入覆盖；测试用独立队列名隔离，
        # 避免与正在运行的服务端 Worker 抢占任务。
        self.queue_keys = dict(queue_keys) if queue_keys else dict(QUEUE_KEYS)

    def _task_key(self, task_id: str)-> str:
        """拼接前缀"""
        return f"{self._task_prefix}{task_id}"

    def create_task(self, user_input: str, session_id: str,
                    lane: str = None) -> dict:
        """创建任务并入队。

        lane 未指定时按关键词预判（guess_lane）；
        入队同时把车道写进任务 Hash，供 Worker 改派与观测。
        """
        task_id = uuid.uuid4().hex
        lane = lane or guess_lane(user_input)
        info = self.client.hset(name=self._task_key(task_id),
                         mapping={
                            "task_id": task_id,
                            "status": "pending",
                            "user_input": user_input,
                            "session_id": session_id,
                            "result": "",
                            "lane": lane,
                            "created_at": str(time.time()),
                          }
                        )
        self.client.expire(self._task_key(task_id), self.expire_seconds)
        self.client.lpush(self.queue_keys[lane], task_id)
        return {"task_id": task_id, "status": "pending", "lane": lane}

    def get_task(self, task_id: str) -> dict:
        data = self.client.hgetall(self._task_key(task_id))
        if not data:
            return None
        result_raw = data.get("result", "")
        if result_raw:
            try:
                data["result"] = json.loads(result_raw)
            except json.JSONDecodeError:
                data["result"] = None
        else:
            data["result"] = None
        return data


    def update_task(self, task_id: str, status: str, result: dict = None) -> None:
        key = self._task_key(task_id)
        mapping = {"status": status}
        if result is not None:
            mapping["result"] = json.dumps(result, ensure_ascii=False)
        self.client.hset(name=key, mapping=mapping)
        self.client.expire(key, self.expire_seconds)

    def dequeue(self, timeout: int = 5, lane: str = LANE_FAST):
        """从指定车道取任务。

        各 Worker 绑定各自车道：快车道 Worker 传 LANE_FAST，慢车道传 LANE_SLOW。
        向后兼容：不传 lane 时行为与旧版一致（消费快车道）。

        注意 timeout 语义：BRPOP 的 timeout=0 在 Redis 里表示**永久阻塞**，
        极易造成调用方卡死。这里约定 timeout<=0 为"非阻塞取一次"（RPOP），
        与直觉一致，也便于测试与优雅退出。
        """
        queue = self.queue_keys.get(lane, self.queue_key)
        if timeout and timeout > 0:
            result = self.client.brpop(queue, timeout=timeout)
            task_id = result[1] if result else None
        else:
            task_id = self.client.rpop(queue)

        if not task_id:
            return None
        task_info = self.get_task(task_id)
        return (task_id, task_info) if task_info else None

    def requeue_to_lane(self, task_id: str, lane: str) -> None:
        """把任务改派到另一条车道（消费侧纠偏）。

        场景：提交时预判进快车道，PLANNING 后发现实际是视频任务——
        快车道 Worker 将其 lpush 回慢车道头部，由慢车道 Worker 接手。
        任务状态重置回 pending。
        """
        self.client.hset(self._task_key(task_id), mapping={
            "status": "pending", "lane": lane,
        })
        self.client.expire(self._task_key(task_id), self.expire_seconds)
        self.client.lpush(self.queue_keys[lane], task_id)
    
    def get_task_by_session(self, session_id: str) -> list:
        """返回指定会话下所有进行中的任务"""
        tasks = []
        for key in self.client.scan_iter(f"{self._task_prefix}*"):
            data = self.client.hgetall(key)
            if data.get("session_id") == session_id and data.get("status") in ("pending", "processing"):
                tasks.append(data)
        return tasks

    # ---- 进度事件通道（工单 T-01）----
    def _progress_key(self, task_id: str) -> str:
        return f"{self._progress_prefix}{task_id}"

    def append_progress(self, task_id: str, event: dict) -> None:
        """追加进度事件到 Redis List，TTL 与任务状态一致（自动过期清理）"""
        key = self._progress_key(task_id)
        self.client.rpush(key, json.dumps(event, ensure_ascii=False))
        self.client.ltrim(key, -500, -1)   # 上限保护
        self.client.expire(key, self.expire_seconds)

    def get_progress(self, task_id: str) -> list:
        """按时间顺序返回进度事件数组"""
        raw = self.client.lrange(self._progress_key(task_id), 0, -1)
        out = []
        for item in raw:
            try:
                out.append(json.loads(item))
            except (json.JSONDecodeError, ValueError):
                continue
        return out

    def _id_map_key(self, external_id: str) -> str:
        return f"{self._id_map_prefix}{external_id}"

    def link_internal_task_id(self, external_id: str, internal_id: str) -> None:
        """登记外部→内部任务ID映射，TTL 与任务一致"""
        key = self._id_map_key(external_id)
        self.client.set(key, internal_id, ex=self.expire_seconds)

    def resolve_internal_task_id(self, external_id: str) -> str:
        """由外部ID解析内部ID；无映射时回退为外部ID本身"""
        return self.client.get(self._id_map_key(external_id)) or external_id