from src.core.models import LLMResponse, TaskResult, CallChainEntry, BuilderInput, Subtask, ExecutionPlan
from src.core.task_router import TaskRouter
from src.core.router import Router
from src.core.llm_client import LLMClient
from src.core.builder import Builder
from src.core.memory import Memory
import time
import uuid
from typing import Callable, Optional


class Agent:
    """负责任务状态机"""

    def __init__(self, task_router: TaskRouter, router: Router, llmclient: LLMClient, builder: Builder, memory: Memory):
        self.task_router = task_router
        self.router = router
        self.llm_client = llmclient
        self.builder = builder
        self.memory = memory

    def run(self, user_input: str, session_id: str, on_progress: Optional[Callable] = None) -> dict:
        """
        READY → PLANNING → ROUTING → CALLING → SUCCESS/PARTIAL_SUCCESS/FAILED

        on_progress 回调接收 dict 事件:
          {"stage": "planning"}
          {"stage": "planned", "count": N}
          {"stage": "routing", "step": i, "total": N}
          {"stage": "calling", "model": "qwen-plus", "step": i, "total": N}
          {"stage": "subtask_done", "step": i, "total": N, "status": "ok"|"fail", "model": "..."}
        """

        def _emit(event: dict):
            if on_progress:
                on_progress(event)

        task_id = "task_" + uuid.uuid4().hex
        results: list[TaskResult] = []
        call_chain: list[CallChainEntry] = []

        # 先保存用户消息到记忆
        if self.memory:
            self.memory.add(session_id, "user", user_input)

        history = self.memory.get_history(session_id) if self.memory else []
        if history:
            full_input = self.memory.build_context(session_id, user_input)
        else:
            full_input = user_input

        # print(f"[DEBUG] 注入的完整上下文:\n{full_input}")  # 临时调试

        # PLANNING
        _emit({"stage": "planning"})
        plan = self.task_router.route_task(full_input)
        if plan and plan.subtasks:
        #     print(f"[DEBUG] TaskRouter 返回的执行计划: intent={plan.intent}, subtasks={[(s.step, s.capability, s.prompt[:60]) for s in plan.subtasks]}")
        # else:
            print(f"[DEBUG] TaskRouter 解析失败，plan={plan}")

        if not plan or not plan.subtasks:
            log = self._log_planning_failure(task_id, user_input, reason="TaskRouter返回为空计划")
            return self._build_response(task_id, "FAILED", results, call_chain, log_override=log)


        total = len(plan.subtasks)
        _emit({"stage": "planned", "count": total})
        step_outputs: dict[int, str] = {}  # step → image_url


        for i, subtask in enumerate(plan.subtasks):
            capability_required = subtask.capability
            prompt = subtask.prompt
            failed_models = []
            success = False

            while not success:
                # ROUTING
                _emit({"stage": "routing", "step": i + 1, "total": total})
                model_info = self.router.get_model(capability_required, failed_models)
                # print(f"[DEBUG] 子任务{i+1} 路由: capability={capability_required}, 选中={model_info.get('registered_name', 'N/A')}, 已排除={failed_models}")

                if "error" in model_info:
                    break

                # CALLING
                _emit({
                    "stage": "calling",
                    "model": model_info["registered_name"],
                    "step": i + 1,
                    "total": total,
                })

                call_image_url = subtask.image_url or ""
                if subtask.reference_step and subtask.reference_step in step_outputs:
                    call_image_url = step_outputs[subtask.reference_step]

                output_type = "text" if capability_required == "text-generation" else "image"
                response = self.llm_client.call(
                    model_name=model_info["model_name"],
                    endpoint=model_info["endpoint"],
                    api_key=model_info["api_key"],
                    prompt=prompt,
                    output_type=output_type,
                    image_url=call_image_url
                )

                attempted_at = str(time.time())
                if response.status == "SUCCESS":
                    call_chain.append(CallChainEntry(
                        model_name=model_info["model_name"],
                        capability=capability_required,
                        status="SUCCESS",
                        attempted_at=attempted_at,
                    ))
                    results.append(response.data)

                    if response.data and response.data.type == "image" and response.data.url:
                        step_outputs[subtask.step] = response.data.url

                    success = True
                    _emit({
                        "stage": "subtask_done",
                        "step": i + 1,
                        "total": total,
                        "status": "ok",
                        "model": model_info["registered_name"],
                    })
                else:
                    call_chain.append(CallChainEntry(
                        model_name=model_info["model_name"],
                        capability=capability_required,
                        status="FAILED",
                        error_code=response.error_code,
                        attempted_at=attempted_at,
                    ))
                    failed_models.append(model_info["registered_name"])
                    # print(f"[DEBUG] 子任务{i+1} 调用失败: model={model_info['registered_name']}, error={response.error_code}, 将尝试下一个模型")
                    _emit({
                        "stage": "subtask_done",
                        "step": i + 1,
                        "total": total,
                        "status": "fail",
                        "model": model_info["registered_name"],
                        "error_code": response.error_code,
                    })

            if not success:
                if results:
                    self.memory.add_assistant_response(session_id, results)
                    return self._build_response(task_id, "PARTIAL_SUCCESS", results, call_chain)
                else:
                    return self._build_response(task_id, "FAILED", results, call_chain)

        self.memory.add_assistant_response(session_id, results)
        return self._build_response(task_id, "SUCCESS", results, call_chain)

    def _log_planning_failure(self, task_id: str, user_input: str, reason: str) ->dict:
        """记录规划失败的日志"""
        return {
            "task_id": task_id,
            "timestamp": str(time.time()),
            "task_status": "FAILED",
            "system_status": "READY",
            "call_chain": [],
            "error_summary": [{"step": 0, "type": "PLANNING_FAILED", "reason": reason}],
        }
        

    def _build_response(self, task_id: str, final_status: str, results: list, call_chain: list, session_id="default", log_override=None) -> dict:
        """拼装 response"""
        if self.builder:
            builder_input = BuilderInput(
                task_id=task_id,
                final_status=final_status,
                results=results,
                call_chain=call_chain,
                session_id=session_id
            )
            return self.builder.build(builder_input)
