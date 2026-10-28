from src.core.agent import Agent
from src.api.task_manager import TaskManager
from src.core.storage import Storage
from src.core.models import TaskResult, CallChainEntry
import threading
import time
import json


class Worker:
    """后台任务消费者：从队列取任务 → 调用 Agent → 写回结果 + 持久化

    双车道（工单 T-05）：
        每个 Worker 实例绑定一条车道（lane），由 main.py 各起一个线程：
        快车道 Worker 消费 agent:queue（text/image），
        慢车道 Worker 消费 agent:queue:slow（video）。
        这样 5 分钟的视频任务只占用慢车道，不再阻塞文本任务。
    """

    def __init__(
        self,
        agent: Agent,
        task_manager: TaskManager,
        storage: Storage,
        stop_event: threading.Event,
        lane: str = "fast",
        requeue_on_mismatch: bool = True,
    ):
        self.agent = agent
        self.task_manager = task_manager
        self.storage = storage
        self.stop_event = stop_event
        self.lane = lane
        # 是否启用消费侧纠偏：快车道捡到视频任务时改派到慢车道
        self.requeue_on_mismatch = requeue_on_mismatch

    def run(self):
        while not self.stop_event.is_set():
            try:
                dequeued = self.task_manager.dequeue(lane=self.lane)
                if dequeued is None:
                    time.sleep(1)
                    continue

                task_id, info = dequeued
                user_input = info["user_input"]
                session_id = info["session_id"]

                # 消费侧纠偏（工单 T-05）：
                # 提交时的车道预判可能失误（关键词未命中但实际是视频任务），
                # 快车道 Worker 捡到这类任务时应改派慢车道，而不是自己跑 5 分钟。
                if self.requeue_on_mismatch and self._should_requeue(info, user_input):
                    self.task_manager.requeue_to_lane(task_id, "slow")
                    continue

                self.task_manager.update_task(task_id, "processing")

                # 进度事件出口（工单 T-01）：此前 agent.run() 未传 on_progress，
                # Orchestrator 发出的 stage/agent 事件全部在进程内蒸发。
                # 现写入 Redis 进度通道，供前端轮询 /progress 实时展示。
                def _make_progress(task_id=task_id):
                    linked = {"done": False}

                    def _on_progress(event: dict):
                        try:
                            payload = dict(event)
                            payload.setdefault("ts", time.time())
                            self.task_manager.append_progress(task_id, payload)

                            # 早期登记内部 ID 映射（T-15）：
                            # Orchestrator 在首个 planning 事件里带出内部 task_id，
                            # 这里立刻登记，使执行期间 /agents 就能关联到
                            # agent_messages（该表是实时写入的），
                            # 而不是等任务结束才登记、执行期间协作视图一直为空。
                            internal_id = payload.get("task_id")
                            if internal_id and not linked["done"]:
                                self.task_manager.link_internal_task_id(
                                    task_id, internal_id
                                )
                                linked["done"] = True
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

    def _should_requeue(self, info: dict, user_input: str) -> bool:
        """判断快车道捡到的任务是否应改派慢车道。

        仅在快车道生效：慢车道 Worker 无论收到什么都自己处理
        （改派慢车道→慢车道会造成死循环）。
        车道判定复用 RedisTaskManager.guess_lane 的规则，保持单一事实来源。
        """
        if self.lane != "fast":
            return False
        try:
            from src.api.redis_task_manager import guess_lane
        except Exception:
            return False
        return guess_lane(user_input) == "slow"
