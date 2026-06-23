from src.core.task_router import TaskRouter
from src.core.router import Router
from src.core.llm_client import LLMClient

router = Router()
client = LLMClient()
tr = TaskRouter(router, client)

plan = tr.route_task("生成一个关于未来城市的图片，并写一段描述")
print(f"意图: {plan.intent}")
print(f"子任务数: {len(plan.subtasks)}")
for s in plan.subtasks:
    print(f"  步骤{s.step}: {s.capability} -> {s.prompt}")