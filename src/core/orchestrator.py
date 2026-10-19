"""Orchestrator（升级计划 4.1 / 阶段三）

由原单 Agent 改造而来：把 ROUTING/CALLING 的职责上移为调度，
专业能力下沉给 Writer/Image/Video/Reviewer 各 Agent。

状态机（升级计划第六章）：
    READY → PLANNING → DISPATCHING → COLLECTING → AUDITING → SUCCESS/PARTIAL_SUCCESS/FAILED

职责边界（严格 SRP）：
    Orchestrator  只做 意图拆解 / 任务派发 / 结果聚合 / 审查仲裁
    专业 Agent    只做 本职生成（各自封装 Prompt 与模型调用）
    MessageBus    只做 消息通道与轨迹记录

兼容性：
    run() 保持与旧 Agent 完全一致的入参与返回契约
    （{"frontend_response": ..., "log_record": ...}），
    因此 Worker / API / 前端零改动即可切换。
"""
import time
import uuid
from typing import Callable, List, Optional

from src.core.contracts import (
    Artifact,
    AgentMessage,
    AgentResponse,
    TaskContext,
    STATUS_SUCCESS,
    STATUS_NEED_REVISION,
    STATUS_FAILED,
)
from src.core.registry import AgentRegistry
from src.core.message_bus import MessageBus
from src.core.task_router import TaskRouter
from src.core.builder import Builder
from src.core.memory import Memory
from src.core.models import (
    BuilderInput,
    CallChainEntry,
    TaskResult,
)
import json


class Orchestrator:
    """多 Agent 编排中枢"""

    #: 能力标签 → 负责该能力的 Agent 名称
    CAPABILITY_TO_AGENT = {
        "text-generation": "writer_agent",
        "image-to-text": "writer_agent",     # 看图写作仍由 Writer 承担
        "image-generation": "image_agent",
        "image-to-video": "video_agent",
        "video-generation": "video_agent",
        "review": "reviewer_agent",
    }

    #: 需要在产物生成后追加审查的步骤（能力）
    REVIEW_AFTER = ("image-generation", "video-generation", "text-generation")

    def __init__(
        self,
        task_router: TaskRouter,
        registry: AgentRegistry,
        message_bus: MessageBus,
        builder: Builder,
        memory: Optional[Memory] = None,
        max_retries: int = 1,
    ):
        self.task_router = task_router
        self.registry = registry
        self.bus = message_bus
        self.builder = builder
        self.memory = memory
        self.max_retries = max_retries

    # ==================================================================
    # 主入口（与旧 Agent.run 契约一致）
    # ==================================================================
    def run(self, user_input: str, session_id: str,
            on_progress: Optional[Callable[[dict], None]] = None) -> dict:
        """READY → PLANNING → DISPATCHING → COLLECTING → AUDITING → 终态"""

        def _emit(event: dict):
            if on_progress:
                on_progress(event)

        task_id = "task_" + uuid.uuid4().hex
        results: List[TaskResult] = []
        call_chain: List[CallChainEntry] = []
        context = TaskContext(
            task_id=task_id, session_id=session_id,
            user_input=user_input, max_retries=self.max_retries,
        )

        if self.memory:
            self.memory.add(session_id, "user", user_input)

        # ---------------- PLANNING ----------------
        _emit({"stage": "planning"})
        full_input = user_input
        if self.memory:
            full_input = self.memory.build_context(session_id, user_input)

        plan = self.task_router.route_task(full_input)
        if not plan or not plan.subtasks:
            return self._planning_failure(task_id, user_input, "TaskRouter返回为空计划")

        total = len(plan.subtasks)
        _emit({"stage": "planned", "count": total})

        step_failed = False      # 有步骤彻底失败
        step_degraded = False    # 有步骤审查打回但重试后交付

        # ---------------- DISPATCHING + COLLECTING ----------------
        # 按步执行：派发给专业 Agent → 回收产物 → 注入下一步上下文
        for i, subtask in enumerate(plan.subtasks):
            agent_name = self.CAPABILITY_TO_AGENT.get(subtask.capability)
            agent = self.registry.get(agent_name) if agent_name else None

            if agent is None:
                return self._planning_failure(
                    task_id, user_input,
                    f"步骤{i + 1}需要能力[{subtask.capability}]，"
                    f"但未注册对应 Agent（{agent_name}）"
                )

            message = AgentMessage(
                task_id=task_id,
                step=subtask.step,
                sender="orchestrator",
                receiver=agent_name,
                prompt=subtask.prompt,
                capability=subtask.capability,
                session_id=session_id,
                # 注入上游产物（含文本），解决步骤间数据传递
                artifacts=context.upstream_of(subtask.step),
            )

            _emit({
                "stage": "dispatching", "step": i + 1, "total": total,
                "agent": agent_name, "capability": subtask.capability,
            })

            # 生成 + 步骤内审查 + 反思重试（升级计划 4.6 闭环）
            response = self.bus.dispatch(message, context)
            step_rejected = False
            attempts = 0

            while True:
                if response.ok:
                    # 本步产物立即送审，审查意见即时回流驱动反思重试
                    audit = self._audit_step(
                        task_id, session_id, subtask, response.artifacts, context, i, total
                    )
                    if audit is None or audit.status != STATUS_NEED_REVISION:
                        break
                    step_rejected = True

                if not context.can_retry(subtask.step):
                    break

                attempts += 1
                context.bump(subtask.step)
                _emit({
                    "stage": "revision", "step": i + 1, "total": total,
                    "agent": agent_name, "attempt": attempts,
                    "issues": response.issues[:3] or (audit.issues[:3] if audit else []),
                })
                # 重做本步：清除本步旧产物，避免失败版本混入下游上下文
                context.step_outputs.pop(subtask.step, None)
                response = self.bus.dispatch(message, context)

            _emit({
                "stage": "collecting", "step": i + 1, "total": total,
                "agent": agent_name, "status": response.status,
            })

            if not response.ok:
                # 本步彻底失败：标记降级，继续后续步骤
                step_failed = True
                continue

            if step_rejected:
                step_degraded = True

            # 产物入上下文（供下游步骤使用）
            context.record(subtask.step, response.artifacts)
            results.extend(a.to_task_result() for a in response.artifacts
                           if a.type in ("text", "image", "video", "file"))

        # ---------------- AUDITING ----------------
        _emit({"stage": "auditing"})
        audit_response = self._audit(task_id, session_id, context, total)
        final_rejected = (
            audit_response is not None
            and audit_response.status == STATUS_NEED_REVISION
        )

        # 汇总调用链（各 Agent 内部收集的模型调用记录）
        call_chain.extend(self.bus.drain_call_chains())
        if audit_response is not None:
            self._append_review_chain(call_chain, audit_response)

        # 仲裁最终状态：
        #   无产物            -> FAILED
        #   有产物且存在降级   -> PARTIAL_SUCCESS（有步骤失败或审查打回）
        #   有产物且全部通过   -> SUCCESS
        if not results:
            final_status = "FAILED"
        elif step_failed or step_degraded or final_rejected:
            final_status = "PARTIAL_SUCCESS"
        else:
            final_status = "SUCCESS"

        if self.memory:
            self.memory.add_assistant_response(session_id, results)

        return self._build_response(task_id, final_status, results, call_chain, user_input)

    # ==================================================================
    # 内部：审查
    # ==================================================================
    def _audit_step(self, task_id: str, session_id: str, subtask,
                    artifacts: List[Artifact], context: TaskContext,
                    idx: int, total: int) -> Optional[AgentResponse]:
        """步骤内审查：生成即送审，审查意见驱动本步反思重试"""
        reviewer = self.registry.get("reviewer_agent")
        if reviewer is None or not artifacts:
            return None
        if subtask.capability not in self.REVIEW_AFTER:
            return None

        msg = AgentMessage(
            task_id=task_id, step=subtask.step, sender="orchestrator",
            receiver="reviewer_agent", prompt="审查本步骤产物",
            capability="review", session_id=session_id, artifacts=artifacts,
        )
        return self.bus.dispatch(msg, context)

    def _audit(self, task_id: str, session_id: str,
               context: TaskContext, total: int) -> Optional[AgentResponse]:
        """对最终产物做一次审查（Reviewer Agent）"""
        reviewer = self.registry.get("reviewer_agent")
        if reviewer is None:
            return None

        artifacts = context.upstream_of(999)   # 收集全部步骤产物
        if not artifacts:
            return None

        msg = AgentMessage(
            task_id=task_id, step=total + 1, sender="orchestrator",
            receiver="reviewer_agent", prompt="审查本次任务的全部产物",
            capability="review", session_id=session_id, artifacts=artifacts,
        )
        return self.bus.dispatch(msg, context)

    @staticmethod
    def _append_review_chain(call_chain: List[CallChainEntry],
                             review: AgentResponse) -> None:
        """把审查结论记入调用链（前端观测看板可见）"""
        if review.status == STATUS_NEED_REVISION:
            call_chain.append(CallChainEntry(
                model_name="(reviewer_rejected)", capability="review",
                status="NEED_REVISION", error_code=None,
                attempted_at=str(time.time()),
            ))

    # ==================================================================
    # 内部：响应拼装（保持旧契约）
    # ==================================================================
    def _planning_failure(self, task_id: str, user_input: str, reason: str) -> dict:
        log = {
            "task_id": task_id,
            "timestamp": str(time.time()),
            "task_status": "FAILED",
            "system_status": "READY",
            "call_chain": [],
            "error_summary": [{"step": 0, "type": "PLANNING_FAILED", "reason": reason}],
        }
        return self._build_response(task_id, "FAILED", [], [], user_input, log_override=log)

    def _build_response(self, task_id: str, final_status: str,
                        results: List[TaskResult], call_chain: List[CallChainEntry],
                        user_input: str, log_override=None) -> dict:
        builder_input = BuilderInput(
            task_id=task_id,
            final_status=final_status,
            results=results,
            call_chain=call_chain,
            session_id="default",
        )
        output = self.builder.build(builder_input)
        # Builder.build 返回 dict（非 BuilderOutput）
        if log_override is not None:
            output["log_record"].update(log_override)
        return output
