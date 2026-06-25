import pytest
from src.core.router import Router
from src.core.llm_client import LLMClient
from src.core.task_router import TaskRouter
from src.core.builder import Builder
from src.core.agent import Agent

@pytest.fixture(scope="module")
def agent():
    """"""
    router = Router()
    llm_client = LLMClient()
    task_router = TaskRouter(router, llm_client)
    builder = Builder()

    agent = Agent(task_router, router, llm_client, builder)
    return agent

@pytest.mark.parametrize("user_input, expected_intent", [
    ("把Hello World翻译成中文", "single_text"),
    ("生成一张小猫的图片", "single_multimodal"),
    ("生成一张小猫的图片，并写一段描述", "multi_step_multimodal"),
])
def test_agent_scenarios(agent, user_input, expected_intent):
    results = agent.run(user_input)

    assert "frontend_response" in results
    assert "log_record" in results

    frontend = results["frontend_response"]
    log = results["log_record"]

    assert "task_id" in frontend
    assert "task_status" in frontend
    assert "system_status" in frontend
    assert "data" in frontend

    assert frontend["task_status"] in ["SUCCESS", "PARTIAL_SUCCESS", "FAILED"]

    assert "call_chain" in log
    assert len(log["call_chain"]) > 0

    assert frontend["system_status"] == "READY"

    print(f"\n[{expected_intent}] 状态: {frontend['task_status']}")
    print(f"调用链: {len(log['call_chain'])} 次调用")


def test_agent_fallback(agent):
    """容错链路"""
    result = agent.run("翻译: Hello World")
    log = result["log_record"]

    # 如果有失败的调用，error_summary 应该记录
    if log["task_status"] == "FAILED":
        assert len(log["error_summary"]) > 0


if __name__ == "__main__":
    pytest.main([__file__,"-v"])


