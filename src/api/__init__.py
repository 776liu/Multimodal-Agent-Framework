from src.core.agent import Agent
from src.core.router import Router
from src.core.llm_client import LLMClient
from src.core.task_router import TaskRouter
from src.core.builder import Builder
from src.core.memory import Memory
from src.core.storage import Storage


def create_agent(db_path: str = "data/agent.db") -> tuple[Agent, Storage]:
    """工厂函数：装配核心引擎依赖链，返回 Agent 和 Storage 实例"""
    router = Router()
    llm_client = LLMClient()
    task_router = TaskRouter(router, llm_client)
    storage = Storage(db_path=db_path)
    builder = Builder()  # 不传 storage — 持久化由 Worker 统一负责
    memory = Memory(max_history=10, storage=storage)
    agent = Agent(task_router, router, llm_client, builder, memory)
    return agent, storage
