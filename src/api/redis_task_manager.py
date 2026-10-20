import uuid
import json
import time
import redis
from src.api.task_manager import TaskManager

class RedisTaskManager(TaskManager):
    """任务管理器:List 做队列,Hash 做状态存储"""
    def __init__(self,
                 host: str = "localhost",
                 port: int = 6379,
                 queue_key: str = "agent:queue",
                 expire_seconds: int = 3600,
                 task_prefix: str = "agent:task:",
                 progress_prefix: str = "agent:progress:",
                 id_map_prefix: str = "agent:idmap:"):
        pool = redis.ConnectionPool(host=host, port=port, decode_responses=True)
        self.client = redis.Redis(connection_pool=pool)
        self.queue_key = queue_key
        self.expire_seconds = expire_seconds
        self._task_prefix = task_prefix
        self._progress_prefix = progress_prefix
        self._id_map_prefix = id_map_prefix

    def _task_key(self, task_id: str)-> str:
        """拼接前缀"""
        return f"{self._task_prefix}{task_id}"

    def create_task(self, user_input: str, session_id: str) ->dict:
        task_id = uuid.uuid4().hex
        info = self.client.hset(name=self._task_key(task_id),
                         mapping={
                            "task_id": task_id,
                            "status": "pending",
                            "user_input": user_input,
                            "session_id": session_id,
                            "result": "",
                            "created_at": str(time.time()),
                          }
                        )        
        self.client.expire(self._task_key(task_id), self.expire_seconds)
        self.client.lpush(self.queue_key, task_id)
        return {"task_id": task_id, "status": "pending"}       

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

    def dequeue(self, timeout: int = 5):
        result = self.client.brpop(self.queue_key, timeout = timeout)
        if result is None:
            return None
        _, task_id = result
        task_info = self.get_task(task_id)
        return (task_id, task_info) if task_info else None
    
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