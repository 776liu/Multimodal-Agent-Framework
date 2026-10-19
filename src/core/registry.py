"""AgentRegistry（升级计划 4.2 上层注册体系）

职责：把"能力标签"映射到具体的专业 Agent 实例。
与下层 Router（能力→模型）形成双层注册：

    Orchestrator ──AgentRegistry──→ WriterAgent / ImageAgent / VideoAgent / ReviewerAgent
                                        └── BaseAgent.execute ──Router──→ 具体大模型

设计要点：
1. 多对多：一个能力可注册多个 Agent（如 text-generation 由 Writer 承担，
   image-to-text 也可由 Writer 承担）；一个 Agent 可承担多个能力。
2. 优先级：同一能力注册多个 Agent 时，按注册顺序取首个可用者。
3. 与 MessageBus 协同：registry 只管寻址，消息分发由 MessageBus 负责。
"""
from typing import Dict, List, Optional

from src.core.base_agent import BaseAgent


class AgentRegistry:
    """专业 Agent 注册中心"""

    def __init__(self):
        self._agents: Dict[str, BaseAgent] = {}              # name -> agent
        self._capability_index: Dict[str, List[str]] = {}    # capability -> [agent_name]

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------
    def register(self, agent: BaseAgent, capabilities: Optional[List[str]] = None) -> None:
        """注册一个 Agent。capabilities 缺省时用 agent 自身的 default_capability"""
        self._agents[agent.name] = agent
        caps = capabilities or [agent.default_capability]
        for cap in caps:
            bucket = self._capability_index.setdefault(cap, [])
            if agent.name not in bucket:
                bucket.append(agent.name)

    def register_all(self, agents: List[BaseAgent]) -> None:
        for a in agents:
            self.register(a)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def find(self, capability: str) -> Optional[BaseAgent]:
        """按能力标签寻址 Agent；找不到返回 None"""
        names = self._capability_index.get(capability)
        if not names:
            return None
        return self._agents.get(names[0])

    def get(self, name: str) -> Optional[BaseAgent]:
        return self._agents.get(name)

    def list_agents(self) -> List[dict]:
        """列出已注册 Agent 及其能力标签（前端观测面板可用）"""
        return [
            {
                "name": name,
                "default_capability": agent.default_capability,
                "capabilities": [c for c, names in self._capability_index.items()
                                 if name in names],
            }
            for name, agent in self._agents.items()
        ]

    def list_capabilities(self) -> List[str]:
        return sorted(self._capability_index.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._agents

    def __len__(self) -> int:
        return len(self._agents)
