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
                 task_prefix: str = "agent:task:"):
        pool = redis.ConnectionPool(host=host, port=port, decode_responses=True)
        self.client = redis.Redis(connection_pool=pool)
        self.queue_key = queue_key
        self.expire_seconds = expire_seconds
        self._task_prefix = task_prefix

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