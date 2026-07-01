import uuid
import time
from abc import ABC, abstractmethod
import threading

class TaskManager(ABC):
    """抽象基类"""

    @abstractmethod
    def create_task(self, user_input: str, session_id:str) ->dict:
        pass

    @abstractmethod
    def get_task(self, task_id: str) ->dict:
        pass

    @abstractmethod
    def update_task(self, task_id: str, status: str, result: dict = None) ->None:
        pass

    @abstractmethod
    def dequeue(self, timeout = 5):
        pass

   

class MemoryTaskManager(TaskManager):
    
    def __init__(self):
        self._tasks = {}
        self._lock = threading.Lock()

    def create_task(self, user_input: str, session_id: str) ->dict:
        task_id = "task_" + uuid.uuid4().hex
        self._tasks[task_id] = {
            "status": "pending",
            "user_input": user_input,
            "session_id": session_id,
            "result": None,
            "created_at": time.time()
        }
        return {"task_id": task_id, "status":"pending"}

    def get_task(self, task_id: str) ->dict:
        return self._tasks.get(task_id)
    
    def update_task(self, task_id: str, status: str, result: dict = None):
        if task_id in self._tasks:
            self._tasks[task_id]["status"] = status
            if result:
                self._tasks[task_id]["result"] = result

    def dequeue(self, timeout=5):
        """
        模拟 BLPOP:返回下一个 pending 任务，没有则等待 timeout 秒后返回 None。
        实际实现可以简单遍历 _tasks 找 status == 'pending' 的第一个任务。
        """
        with self._lock:
            for task_id, info in self._tasks.items():
                if info["status"] == "pending":
                    return task_id, info
        time.sleep(timeout)
        return None

    def get_task_by_session(self, session_id):
        tasks = []
        for task_id, info in self._tasks.items():
            if info.get("session_id") == session_id and info.get("status") in ("pending", "processing"):
                tasks.append({"task_id": task_id, **info})
        return tasks

