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

    def requeue_to_lane(self, task_id: str, lane: str) -> None:
        """把任务改派到指定车道（双车道，工单 T-05）

        默认空实现：不支持分车道的实现（如内存版以外的旧实现）可安全继承。
        """
        return None

    # ---- 进度事件通道（工单 T-01）----
    # 默认实现为内存版，RedisTaskManager 会覆盖为 Redis 版；
    # 两者接口一致，Worker 无需感知底层是哪种实现。

    @abstractmethod
    def append_progress(self, task_id: str, event: dict) -> None:
        """追加一条进度事件"""

    @abstractmethod
    def get_progress(self, task_id: str) -> list:
        """按时间顺序返回进度事件数组"""

    @abstractmethod
    def link_internal_task_id(self, external_id: str, internal_id: str) -> None:
        """登记外部任务ID → 引擎内部任务ID 的映射

        背景: Redis 队列ID 与 Orchestrator 内部生成的 task_id 是两套 ID，
        而 agent_messages 表记录的是内部 ID。
        前端只有外部ID，需要此映射才能查到多 Agent 轨迹。
        """

    @abstractmethod
    def resolve_internal_task_id(self, external_id: str) -> str:
        """由外部任务ID解析内部任务ID；无映射时回退为外部ID本身"""

   

class MemoryTaskManager(TaskManager):
    
    def __init__(self):
        self._tasks = {}
        self._lock = threading.Lock()
        self._progress = {}      # task_id -> [event]
        self._progress_ts = {}   # task_id -> 最后写入时间
        self._id_map = {}        # 外部任务ID -> 引擎内部任务ID
        self._lanes = {}         # task_id -> lane（双车道模拟，工单 T-05）

    def create_task(self, user_input: str, session_id: str,
                    lane: str = None) ->dict:
        task_id = "task_" + uuid.uuid4().hex
        self._tasks[task_id] = {
            "status": "pending",
            "user_input": user_input,
            "session_id": session_id,
            "result": None,
            "created_at": time.time()
        }
        self._lanes[task_id] = lane or "fast"
        return {"task_id": task_id, "status":"pending", "lane": self._lanes[task_id]}

    def get_task(self, task_id: str) ->dict:
        return self._tasks.get(task_id)
    
    def update_task(self, task_id: str, status: str, result: dict = None):
        if task_id in self._tasks:
            self._tasks[task_id]["status"] = status
            if result:
                self._tasks[task_id]["result"] = result

    def dequeue(self, timeout=5, lane=None):
        """取出指定车道下一个 pending 任务；lane 为 None 时不限车道。

        双车道语义与 RedisTaskManager 对齐：Worker 绑定车道后只消费本车道任务。
        """
        with self._lock:
            for task_id, info in self._tasks.items():
                if info["status"] != "pending":
                    continue
                if lane is not None and self._lanes.get(task_id) != lane:
                    continue
                return task_id, info
        time.sleep(timeout)
        return None

    def requeue_to_lane(self, task_id: str, lane: str) -> None:
        """改派任务到指定车道（内存实现）"""
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["status"] = "pending"
            self._lanes[task_id] = lane

    def get_task_by_session(self, session_id):
        tasks = []
        for task_id, info in self._tasks.items():
            if info.get("session_id") == session_id and info.get("status") in ("pending", "processing"):
                tasks.append({"task_id": task_id, **info})
        return tasks

    # ---- 进度事件（内存实现）----
    def append_progress(self, task_id: str, event: dict) -> None:
        with self._lock:
            self._progress.setdefault(task_id, []).append(event)
            self._progress_ts.setdefault(task_id, time.time())
            # 上限保护：避免异常场景下无限增长
            if len(self._progress[task_id]) > 500:
                self._progress[task_id] = self._progress[task_id][-500:]

    def get_progress(self, task_id: str) -> list:
        return list(self._progress.get(task_id, []))

    # ---- 任务ID映射（内存实现）----
    def link_internal_task_id(self, external_id: str, internal_id: str) -> None:
        with self._lock:
            self._id_map[external_id] = internal_id

    def resolve_internal_task_id(self, external_id: str) -> str:
        return self._id_map.get(external_id, external_id)

