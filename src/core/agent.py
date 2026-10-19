from src.core.models import TaskResult, CallChainEntry, BuilderInput, Subtask, ExecutionPlan
from src.core.task_router import TaskRouter
from src.core.router import Router
from src.core.llm_client import LLMClient
from src.core.builder import Builder
from src.core.memory import Memory
from src.core.evaluator import Evaluator
import time
import uuid
from typing import Callable, Optional


# capability → LLMClient 输出协议类型 的映射表
# 注意: capability 与 output_type 是两套命名，不能直接透传
#   text-generation / image-to-text  -> "text"
#   image-generation                  -> "image"
#   video-generation / image-to-video -> "video"
OUTPUT_TYPE_MAP = {
    "text-generation": "text",
    "image-to-text": "text",
    "image-generation": "image",
    "video-generation": "video",
    "image-to-video": "video",
}


class Agent:
    """负责任务状态机"""

    def __init__(self, task_router: TaskRouter, router: Router, llmclient: LLMClient, builder: Builder, memory: Memory, evaluator: Optional[Evaluator] = None):
        self.task_router = task_router
        self.router = router
        self.llm_client = llmclient
        self.builder = builder
        self.memory = memory
        self.evaluator = evaluator

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


        # PLANNING
        _emit({"stage": "planning"})
        plan = self.task_router.route_task(full_input)
        if not plan or not plan.subtasks:
            log = self._log_planning_failure(task_id, user_input, reason="TaskRouter返回为空计划")
            return self._build_response(task_id, "FAILED", results, call_chain, user_input, log_override=log)


        total = len(plan.subtasks)
        _emit({"stage": "planned", "count": total})
        step_outputs: dict[int, str] = {}  # step → image_url


        for i, subtask in enumerate(plan.subtasks):
            capability_required = subtask.capability
            prompt = subtask.prompt
            failed_models = []
            success = False
            _no_model_reason = None

            while not success:
                # ROUTING
                _emit({"stage": "routing", "step": i + 1, "total": total})

                # 先解析本步实际输入图片（可能来自子任务自带或前序步骤产物），
                # 再决定路由标签：带图的文本任务走 image-to-text (VLM)
                call_image_url = subtask.image_url or ""
                if subtask.reference_step and subtask.reference_step in step_outputs:
                    call_image_url = step_outputs[subtask.reference_step]

                routing_capability = capability_required
                if capability_required == "text-generation" and call_image_url:
                    routing_capability = "image-to-text"
                elif capability_required == "video-generation" and call_image_url:
                    # 图生视频：带参考帧时优先路由 I2V 模型
                    routing_capability = "image-to-video"

                model_info = self.router.get_model(routing_capability, failed_models)

                if "error" in model_info:
                    # VLM / I2V 专属池耗尽时回退到通用池兜底（宁可重试也不直接失败）
                    if routing_capability in ("image-to-text", "image-to-video"):
                        fallback_cap = (
                            "text-generation" if routing_capability == "image-to-text"
                            else "video-generation"
                        )
                        model_info = self.router.get_model(fallback_cap, failed_models)
                    if "error" in model_info:
                        # 无模型可用：写入语义化失败原因，不再让 Builder 输出
                        # 笼统的"服务暂时不可用"
                        _no_model_reason = (
                            f"步骤{i + 1}需要能力[{routing_capability}]，"
                            "但模型注册表中无可用模型（未配置或已全部失败）"
                        )
                        call_chain.append(CallChainEntry(
                            model_name="(no-model-available)",
                            capability=routing_capability,
                            status="FAILED",
                            error_code=-2,
                            attempted_at=str(time.time()),
                        ))
                        break

                # CALLING
                _emit({
                    "stage": "calling",
                    "model": model_info["registered_name"],
                    "step": i + 1,
                    "total": total,
                })

                # 输出类型按 capability 映射到 LLMClient 支持的协议类型
                # 见模块级 OUTPUT_TYPE_MAP 注释
                output_type = OUTPUT_TYPE_MAP.get(capability_required)
                if output_type is None:
                    # 未知 capability：记录语义化失败原因，避免以 -1 静默失败
                    _no_model_reason = (
                        f"步骤{i + 1}的能力[{capability_required}]没有对应的输出协议映射"
                    )
                    call_chain.append(CallChainEntry(
                        model_name="(unsupported-capability)",
                        capability=capability_required,
                        status="FAILED",
                        error_code=-3,
                        attempted_at=str(time.time()),
                    ))
                    break

                # 视频生成耗时较长(约5分钟)，提前告知前端进入长任务等待
                if output_type == "video":
                    _emit({
                        "stage": "video_rendering",
                        "step": i + 1,
                        "total": total,
                        "model": model_info["registered_name"],
                        "notice": "视频生成中，通常需要 3-6 分钟",
                    })

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
                    if self.memory:
                        self.memory.add_assistant_response(session_id, results)
                    return self._build_response(task_id, "PARTIAL_SUCCESS", results, call_chain, user_input)
                else:
                    # 无任何产物时，把具体失败原因注入日志（前端可见）
                    log_override = None
                    if _no_model_reason:
                        log_override = {
                            "task_id": task_id,
                            "timestamp": str(time.time()),
                            "task_status": "FAILED",
                            "system_status": "READY",
                            "call_chain": [
                                {"model_name": c.model_name, "capability": c.capability,
                                 "status": c.status, "error_code": c.error_code,
                                 "attempted_at": c.attempted_at}
                                for c in call_chain
                            ],
                            "error_summary": [{
                                "step": i + 1,
                                "type": "NO_AVAILABLE_MODEL",
                                "capability": routing_capability,
                                "reason": _no_model_reason,
                            }],
                        }
                    return self._build_response(task_id, "FAILED", results, call_chain, user_input, log_override=log_override)

        if self.memory:
            self.memory.add_assistant_response(session_id, results)
        return self._build_response(task_id, "SUCCESS", results, call_chain, user_input)

    def _log_planning_failure(self, task_id: str, user_input: str, reason: str) -> dict:
        """记录规划失败的日志"""
        return {
            "task_id": task_id,
            "timestamp": str(time.time()),
            "task_status": "FAILED",
            "system_status": "READY",
            "call_chain": [],
            "error_summary": [{"step": 0, "type": "PLANNING_FAILED", "reason": reason}],
        }
        

    def _build_response(self, 
                        task_id: str, 
                        final_status: str, 
                        results: list, 
                        call_chain: list,
                        user_input: str,
                        session_id="default", 
                        log_override=None,                   
                        ) -> dict:
        """拼装 response"""
        if self.builder:
            builder_input = BuilderInput(
                task_id=task_id,
                final_status=final_status,
                results=results,
                call_chain=call_chain,
                session_id=session_id
            )
            output = self.builder.build(builder_input)
            if self.evaluator:
                self.evaluator.audit(task_id, user_input, output.frontend_response)
            return output
