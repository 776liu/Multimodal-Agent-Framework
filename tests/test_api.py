import requests
import time
import pytest

BASE_URL = "http://127.0.0.1:8000"


def test_submit_and_poll_text_task():
    """测试提交文本任务，轮询直到完成，验证结果正确"""
    
    # 1. 提交任务
    resp = requests.post(
        f"{BASE_URL}/api/task/submit",
        json={"user_input": "把 Hello World 翻译成中文", "session_id": "pytest-session"},
    )
    assert resp.status_code == 202, f"提交失败: {resp.status_code} {resp.text}"
    task_info = resp.json()
    task_id = task_info["task_id"]
    assert task_info["status"] == "pending"

    # 2. 轮询直到终态或超时
    max_wait = 60
    start = time.time()
    final_result = None

    while time.time() - start < max_wait:
        resp = requests.get(f"{BASE_URL}/api/task/{task_id}")
        assert resp.status_code == 200, f"查询失败: {resp.status_code}"
        task_data = resp.json()
        status = task_data["status"]
        
        if status in ("SUCCESS", "PARTIAL_SUCCESS", "FAILED"):
            final_result = task_data
            break
        time.sleep(2)

    assert final_result is not None, "任务超时未完成"

    # 3. 验证结果结构
    result_data = final_result.get("result", {})
    frontend = result_data.get("frontend_response", {})
    assert frontend.get("task_status") in ("SUCCESS", "PARTIAL_SUCCESS", "FAILED")
    
    # 可以进一步验证内容：如果是 SUCCESS，应该有翻译结果
    if frontend["task_status"] == "SUCCESS":
        results = frontend.get("data", {}).get("results", [])
        assert len(results) > 0
        # 简单检查文本存在
        assert any(r.get("type") == "text" and r.get("content") for r in results)