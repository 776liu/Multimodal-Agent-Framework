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

                # 进度事件出口（工单 T-01）：此前 agent.run() 未传 on_progress，
                # Orchestrator 发出的 stage/agent 事件全部在进程内蒸发。
                # 现写入 Redis 进度通道，供前端轮询 /progress 实时展示。
                def _make_progress(task_id=task_id):
                    def _on_progress(event: dict):
                        try:
                            payload = dict(event)
                            payload.setdefault("ts", time.time())
                            self.task_manager.append_progress(task_id, payload)
                        except Exception:
                            pass  # 进度记录失败不阻断任务
                    return _on_progress

                try:
                    result = self.agent.run(user_input, session_id,
                                            on_progress=_make_progress())

                    # 登记 外部任务ID → 引擎内部task_id 映射（工单 T-01）：
                    # agent_messages / task_logs 记录的是内部ID，
                    # 前端持有的却是 Redis 队列的外部ID，需要映射才能关联查询
                    internal_id = (result.get("log_record") or {}).get("task_id")
                    if internal_id:
                        try:
                            self.task_manager.link_internal_task_id(task_id, internal_id)
                        except Exception:
                            pass
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
                    # 标签回填：会话标签仍为默认值时，用首条用户消息作为标签
                    self.storage.backfill_session_label(session_id, user_input)
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
