"""MessageBus（升级计划 4.3 / 阶段一）

设计取舍：星型拓扑（Hub-and-Spoke），不做去中心化广播。
- Orchestrator 是唯一 Hub，负责派发与回收；
- Agent 之间不直接通信，所有数据流经 Hub 中转。

理由（对应升级计划中的设计约束）：
1. 可追踪性：每次交互都落在 Hub 上，天然形成完整调用链，论文可观测性友好；
2. 顺序确定：DAG 执行顺序由 Orchestrator 控制，避免竞态；
3. 零运维成本：进程内实现，不引入外部 MQ，避免过度设计。

本阶段（阶段一）只提供消息通道与落库能力，
真正的 Agent 调度接入放在阶段三。
"""
from typing import Callable, Dict, List, Optional

from src.core.contracts import (
    AgentMessage,
    AgentResponse,
    Artifact,
    STATUS_SUCCESS,
)
from src.core.base_agent import BaseAgent


class MessageBus:
    """Orchestrator 与各专业 Agent 之间的消息总线"""

    def __init__(self, storage=None):
        self.storage = storage
        # receiver 名称 -> Agent 实例（阶段三由 AgentRegistry 填充）
        self.agents: Dict[str, BaseAgent] = {}
        # 本次任务的消息轨迹（内存态，任务结束后清空）
        self.trace: List[dict] = []

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------
    def register(self, agent: BaseAgent) -> None:
        """注册一个专业 Agent"""
        self.agents[agent.name] = agent

    def has_agent(self, name: str) -> bool:
        return name in self.agents

    # ------------------------------------------------------------------
    # 派发与回收（星型拓扑的唯一通道）
    # ------------------------------------------------------------------
    def dispatch(self, message: AgentMessage, context) -> AgentResponse:
        """派发消息给目标 Agent 并等待其响应（同步语义）。

        与现有单 Agent 架构一致：Worker 线程内顺序执行，
        因此无需异步队列；异步化留给阶段四的 SSE 推送。
        """
        agent = self.agents.get(message.receiver)
        if agent is None:
            resp = AgentResponse.failed(
                message.receiver,
                error_code=-2,
                issues=[f"未注册的 Agent: {message.receiver}"],
            )
            self._record(message, resp)
            return resp

        self._record(message, None)          # 记录派发
        response = agent.execute(message, context)
        self._record(message, response)      # 记录回收
        return response

    def collect_artifacts(self, responses: List[AgentResponse]) -> List[Artifact]:
        """把多个 Agent 响应中的产物汇总为一个列表，供下游步骤使用。

        这是解决"步骤间产物传递"的核心方法：
        Orchestrator 在 Step N 结束后调用，把产物注入 Step N+1 的消息。
        """
        out: List[Artifact] = []
        for r in responses:
            if r.ok:
                out.extend(r.artifacts)
        return out

    # ------------------------------------------------------------------
    # 内部：轨迹记录 + 落库
    # ------------------------------------------------------------------
    def _record(self, message: AgentMessage,
                response: Optional[AgentResponse]) -> None:
        entry = {
            "task_id": message.task_id,
            "step": message.step,
            "from": message.sender,
            "to": message.receiver,
            "prompt": message.prompt,
            "capability": message.capability,
            "reference_step": message.reference_step,
            "input_artifacts": [a.to_dict() for a in message.artifacts],
            "status": response.status if response else "DISPATCHED",
            "output_artifacts": [a.to_dict() for a in response.artifacts] if response else [],
            "issues": list(response.issues) if response else [],
            "error_code": response.error_code if response else None,
        }
        self.trace.append(entry)

        if self.storage is None:
            return

        if response is None:
            # 派发记录：执行方 = 收件 Agent
            self.storage.save_agent_message(
                task_id=message.task_id,
                session_id=message.session_id,
                from_agent=message.sender,
                to_agent=message.receiver,
                step=message.step,
                message_type="dispatch",
                content=message.prompt,
                artifacts=entry["input_artifacts"],
                role=message.receiver,
                reference_step=message.reference_step,
            )
        elif response.ok:
            # 成功回收：执行方 = 发件 Agent
            self.storage.save_agent_message(
                task_id=message.task_id,
                session_id=message.session_id,
                from_agent=message.receiver,
                to_agent=message.sender,
                step=message.step,
                message_type="result",
                content=response.output_text[:2000],
                artifacts=entry["output_artifacts"],
                status=STATUS_SUCCESS,
                role=message.receiver,
                reference_step=message.reference_step,
            )
        else:
            # 失败/打回
            self.storage.save_agent_message(
                task_id=message.task_id,
                session_id=message.session_id,
                from_agent=message.receiver,
                to_agent=message.sender,
                step=message.step,
                message_type="result",
                content=response.output_text[:2000],
                artifacts=entry["output_artifacts"],
                status=response.status,
                issues=response.issues,
                role=message.receiver,
                reference_step=message.reference_step,
            )

    def drain_trace(self) -> List[dict]:
        """取走并清空轨迹（任务结束时由 Orchestrator 取走）"""
        t, self.trace = self.trace, []
        return t

    def drain_call_chains(self) -> List:
        """汇总所有已注册 Agent 的调用链"""
        chains = []
        for agent in self.agents.values():
            chains.extend(agent.drain_call_chain())
        return chains
