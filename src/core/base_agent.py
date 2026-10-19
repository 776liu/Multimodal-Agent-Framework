"""多 Agent 基类（升级计划 阶段一 / 4.1）

职责边界：
- Orchestrator 只做派发与聚合，不含业务逻辑；
- 每个专业 Agent（Writer/Image/Video/Reviewer）继承 BaseAgent，
  只需实现 `_run()` 处理具体业务；
- 基类统一负责：模型路由、重试降级、结果包装、调用链记录。

新增能力对比现状：
现状 Agent 里手写的「while not success / failed_models / call_chain.append」循环，
在本基类中收敛为一次 execute() 调用，专业 Agent 不必重复这套样板。
"""
from abc import ABC, abstractmethod
from typing import List, Optional

from src.core.contracts import (
    Artifact,
    AgentMessage,
    AgentResponse,
    TaskContext,
    STATUS_SUCCESS,
    STATUS_FAILED,
)
from src.core.router import Router
from src.core.llm_client import LLMClient
from src.core.models import CallChainEntry

import time


class BaseAgent(ABC):
    """所有专业 Agent 的抽象基类"""

    # 子类声明：默认按哪个能力标签路由模型
    default_capability: str = "text-generation"

    def __init__(
        self,
        name: str,
        router: Router,
        llm_client: LLMClient,
        capability: Optional[str] = None,
    ):
        self.name = name
        self.router = router
        self.llm_client = llm_client
        self.capability = capability or self.default_capability
        # 调用链收集器，由 Orchestrator 在任务结束后取走落库
        self.call_chain: List[CallChainEntry] = []

    # ------------------------------------------------------------------
    # 子类实现入口
    # ------------------------------------------------------------------
    @abstractmethod
    def _run(self, message: AgentMessage, context: TaskContext,
             model_info: dict) -> AgentResponse:
        """执行具体业务。model_info 为 Router 已选定的模型信息。

        子类应把结果包装成 AgentResponse（可用 success/failed 便捷方法），
        并通过 response.artifacts 返回产物，由基类统一收集。
        """

    # ------------------------------------------------------------------
    # 基类统一执行流程：路由 → 调用 → 降级重试 → 结果包装
    # ------------------------------------------------------------------
    def execute(self, message: AgentMessage, context: TaskContext) -> AgentResponse:
        """统一执行入口，由 Orchestrator 调用。失败自动降级换模型重试。"""
        capability = self.resolve_capability(message)

        failed_models: List[str] = []
        last_response: Optional[AgentResponse] = None

        while True:
            model_info = self.router.get_model(capability, failed_models)

            if "error" in model_info:
                if last_response is not None:
                    # 已尝试过：返回最后一次失败
                    return last_response
                return AgentResponse.failed(
                    self.name,
                    error_code=-2,
                    issues=[f"能力[{capability}]在模型注册表中无可用模型"],
                )

            try:
                response = self._run(message, context, model_info)
            except Exception as exc:  # 子类异常兜底，转为标准失败响应
                response = AgentResponse.failed(self.name, error_code=-1, issues=[str(exc)])

            if response.ok:
                self._record_chain(model_info, capability, "SUCCESS")
                return response

            last_response = response
            self._record_chain(model_info, capability, "FAILED", response.error_code)
            failed_models.append(model_info["registered_name"])

            # 失败且仍可重试 → 换模型；否则终止
            if not context.can_retry(message.step):
                return response

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------
    def resolve_capability(self, message: AgentMessage) -> str:
        """决定本步的路由标签。

        默认直接用自身能力；若消息带有图片输入且本 Agent 支持视觉，
        需子类覆写（如 Writer Agent 的 image-to-text 路由）。
        """
        return self.capability

    def _record_chain(self, model_info: dict, capability: str, status: str,
                      error_code: Optional[int] = None) -> None:
        """记录一条调用链（供 Orchestrator 汇总落库）"""
        self.call_chain.append(CallChainEntry(
            model_name=model_info.get("model_name", "unknown"),
            capability=capability,
            status=status,
            error_code=error_code,
            attempted_at=str(time.time()),
        ))

    def artifacts_from_response(self, response: AgentResponse) -> List[Artifact]:
        if response.ok and response.artifacts:
            return response.artifacts
        return []

    def drain_call_chain(self) -> List[CallChainEntry]:
        """取走并清空调用链（Orchestrator 在任务结束时调用）"""
        chain, self.call_chain = self.call_chain, []
        return chain
