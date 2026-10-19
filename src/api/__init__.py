from src.core.agent import Agent
from src.core.router import Router
from src.core.llm_client import LLMClient
from src.core.task_router import TaskRouter
from src.core.builder import Builder
from src.core.memory import Memory
from src.core.storage import Storage

# 多 Agent 编排组件
from src.core.registry import AgentRegistry
from src.core.message_bus import MessageBus
from src.core.orchestrator import Orchestrator
from src.core.agents import WriterAgent, ImageAgent, VideoAgent, ReviewerAgent


def create_agent(db_path: str = "data/agent.db", multi_agent: bool = True,
                 max_retries: int = 1):
    """工厂函数：装配核心引擎依赖链。

    multi_agent=False → 返回旧单 Agent（向后兼容，便于论文做基线对比实验）
    multi_agent=True  → 返回 Orchestrator 多 Agent 编排器

    两者 run() 的入参与返回契约完全一致
    （user_input, session_id, on_progress）→ {"frontend_response", "log_record"}，
    因此 Worker / API / 前端无需任何改动即可切换。
    """
    router = Router()
    llm_client = LLMClient()
    task_router = TaskRouter(router, llm_client)
    storage = Storage(db_path=db_path)
    builder = Builder()  # 不传 storage — 持久化由 Worker 统一负责
    memory = Memory(max_history=10, storage=storage)

    if not multi_agent:
        return Agent(task_router, router, llm_client, builder, memory), storage

    # ---- 多 Agent 装配 ----
    registry = AgentRegistry()
    registry.register_all([
        WriterAgent(router, llm_client),
        ImageAgent(router, llm_client),
        VideoAgent(router, llm_client),
        ReviewerAgent(router, llm_client),
    ])

    bus = MessageBus(storage=storage)
    for name in ("writer_agent", "image_agent", "video_agent", "reviewer_agent"):
        if name in registry:
            bus.register(registry.get(name))

    orchestrator = Orchestrator(
        task_router=task_router,
        registry=registry,
        message_bus=bus,
        builder=builder,
        memory=memory,
        max_retries=max_retries,
    )
    return orchestrator, storage
