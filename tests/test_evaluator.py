import pytest
from src.core.storage import Storage
from src.core.evaluator import Evaluator


@pytest.fixture
def storage():
    """创建测试用 Storage 实例，每个测试前清理 audit 旧数据"""
    s = Storage(db_path="data/test_agent.db")
    with s._get_conn() as conn:
        conn.execute("DELETE FROM task_audits")
    return s


@pytest.fixture
def evaluator(storage):
    """创建 Evaluator 实例"""
    return Evaluator(storage)


def test_rule_audit_success(evaluator, storage):
    """验证用例1：规则审计成功"""
    task_id = "test-audit-001"
    evaluator.audit(
        task_id=task_id,
        user_input="翻译 Hello World",
        frontend_response={
            "data": {
                "results": [
                    {"type": "text", "content": "你好，世界！这是一个翻译测试。"}
                ]
            }
        }
    )

    audits = evaluator.get_audit_report(task_id)
    assert len(audits) == 1
    assert audits[0]["task_id"] == task_id
    assert audits[0]["audit_type"] == "rule"
    assert audits[0]["quality_score"] == 5.0
    assert audits[0]["issues"] == []


def test_rule_audit_issues(evaluator, storage):
    """规则检查发现问题"""
    task_id = "test-audit-002"
    evaluator.audit(
        task_id=task_id,
        user_input="测试空结果",
        frontend_response={"data": {"results": []}}
    )

    audits = evaluator.get_audit_report(task_id)
    assert len(audits) == 1
    assert audits[0]["quality_score"] < 5.0
    assert len(audits[0]["issues"]) > 0
    assert any("未返回" in issue for issue in audits[0]["issues"])


def test_human_feedback_success(evaluator, storage):
    """人工反馈记录成功"""
    task_id = "test-audit-003"
    evaluator.record_feedback(
        task_id=task_id,
        human_score=4.0,
        correction="翻译不够地道"
    )

    audits = evaluator.get_audit_report(task_id)
    assert len(audits) == 1
    assert audits[0]["audit_type"] == "human"
    assert audits[0]["quality_score"] == 4.0
    assert audits[0]["human_feedback"]["score"] == 4.0
    assert audits[0]["human_feedback"]["correction"] == "翻译不够地道"


def test_audit_does_not_block(evaluator, storage):
    """审计异常不阻塞主流程"""
    task_id = "test-audit-004"

    # 模拟一个会导致 audit 内部出错但不应抛异常的场景
    try:
        evaluator.audit(
            task_id=task_id,
            user_input="测试异常",
            frontend_response=None  # 故意传 None，触发内部异常
        )
    except Exception:
        pytest.fail("audit() 不应该抛出异常")

    # 即使审计异常，也不影响后续操作
    assert evaluator.get_audit_report(task_id) == []


def test_human_feedback_without_correction(evaluator, storage):
    """验证用例2-补充：人工反馈不包含纠正文本"""
    task_id = "test-audit-005"
    evaluator.record_feedback(task_id=task_id, human_score=3.0)

    audits = evaluator.get_audit_report(task_id)
    assert len(audits) == 1
    assert audits[0]["quality_score"] == 3.0
    assert audits[0]["human_feedback"]["score"] == 3.0
    assert audits[0]["human_feedback"].get("correction") is None