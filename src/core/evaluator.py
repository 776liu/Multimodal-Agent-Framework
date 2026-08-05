from typing import List, Optional
from src.core.storage import Storage

class Evaluator:
    """审计模块"""

    def __init__(self, storage: Storage):
        self.storage = storage

    def audit(self, 
              task_id: str, 
              user_input: str, 
              frontend_response: dict
            ) -> None:
        """
        对 Agent 执行结果进行自动审计。
        当前实现：规则检查
        审计失败时静默跳过，不阻断主流程。
        """
        try:
            issues: List[str] = []
            data = frontend_response.get("data", {})
            results = data.get("results", [])

            if not results:
                issues.append("Agent 未返回任何生成结果")
            else:
                for item in results:
                    if item.get("type") == "text":
                        content = item.get("content", "")
                        if len(content) < 10:
                            issues.append(f"文本内容过短（{len(content)} 字符）")

            quality_score = max(0.0, 5.0 - len(issues) * 0.5)

            self.storage.save_audit(
                task_id = task_id,
                audit_type = "rule",
                quality_score = quality_score,
                issues = issues if issues else None
            )
            
        except Exception:
            pass
    
        
    def record_feedback(self, 
                        task_id: str, 
                        human_score: float, 
                        correction: Optional[str] = None
                        ) -> None:
        try:
            feedback = {"score": human_score}
            if correction:
                feedback["correction"] = correction

            self.storage.save_audit(
                task_id = task_id,
                audit_type = "human",
                quality_score = human_score,
                issues = None,
                human_feedback = feedback
            )
        except Exception: 
            pass

    def get_audit_report(self, task_id: str) -> List[dict]:
        return self.storage.get_audits(task_id)
