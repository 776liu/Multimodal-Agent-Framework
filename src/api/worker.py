from src.core.agent import Agent
from src.api.task_manager import TaskManager
from src.core.storage import Storage
from src.core.models import TaskResult, CallChainEntry
import threading
import time
import json


class Worker:
    """后台任务消费者：从队列取任务 → 调用 Agent → 写回结果 + 持久化"""

    def __init__(
        self,
        agent: Agent,
        task_manager: TaskManager,
        storage: Storage,
        stop_event: threading.Event,
    ):
        self.agent = agent
        self.task_manager = task_manager
        self.storage = storage
        self.stop_event = stop_event

    def run(self):
        while not self.stop_event.is_set():
            try:
                dequeued = self.task_manager.dequeue()
                if dequeued is None:
                    time.sleep(1)
                    continue

                task_id, info = dequeued
                user_input = info["user_input"]
                session_id = info["session_id"]

                self.task_manager.update_task(task_id, "processing")

                try:
                    result = self.agent.run(user_input, session_id)
                    final_status = result["frontend_response"]["task_status"]
                    self.task_manager.update_task(task_id, final_status, result)

                    frontend = result["frontend_response"]
                    log = result["log_record"]

                    results_objs = [
                        TaskResult(**r)
                        for r in frontend.get("data", {}).get("results", [])
                    ]
                    chain_objs = [
                        CallChainEntry(**c)
                        for c in log.get("call_chain", [])
                    ]

                    self.storage.save_message(session_id, "user", user_input)
                    self.storage.save_message(
                        session_id, "assistant",
                        json.dumps(frontend.get("data", {}), ensure_ascii=False),
                    )
                    self.storage.save_task_log(
                        task_id,
                        session_id,
                        frontend,
                        log,
                        results=results_objs,
                        call_chain=chain_objs,
                        user_input=user_input,
                    )
                except Exception as e:
                    self.task_manager.update_task(task_id, "FAILED", {"error": str(e)})
            except Exception:
                time.sleep(1)
