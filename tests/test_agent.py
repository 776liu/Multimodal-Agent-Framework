import pytest
from src.core.router import Router
from src.core.llm_client import LLMClient
from src.core.task_router import TaskRouter
from src.core.builder import Builder
from src.core.agent import Agent
from src.adapters.config import load_model_config

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


def test_agent_fallback_success():
    """覆盖容错链路中模型降级"""
    test_models = load_model_config("config/model.test.yaml")

    # 规划用 Router（只含可达模型，确保 TaskRouter 不因 key 问题挂掉）
    planning_models = [m for m in test_models if m.registered_name == "task-router-model"]
    planning_router = Router(models=planning_models)

    # 执行用 Router（含不可达首选 + 可达备选，验证降级逻辑）
    exec_models = [m for m in test_models if m.registered_name != "task-router-model"]
    exec_router = Router(models=exec_models)

    builder = Builder()
    llm_client = LLMClient()
    task_router = TaskRouter(planning_router, llm_client)
    agent = Agent(task_router, exec_router, llm_client, builder)

    results = agent.run("翻译:Hello World")
    frontend = results["frontend_response"]
    log = results["log_record"]

    assert frontend["task_status"] == "SUCCESS"

    status = [c["status"]for c in log["call_chain"]]
    assert "FAILED" in status
    assert "SUCCESS" in status

    assert status[0] == "FAILED"
    assert status[-1] == "SUCCESS"

    assert len(log["error_summary"]) == 1
    assert log["error_summary"][0]["model_name"] == "qwen3.7-plus"

    assert len(frontend["data"]["results"]) == 1
    assert frontend["data"]["results"][0]["type"] == "text"
    assert len(frontend["data"]["results"][0]["content"]) > 0

    assert frontend["system_status"] == "READY"

if __name__ == "__main__":
    pytest.main([__file__,"-v"])


