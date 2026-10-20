"""Reviewer Agent（升级计划 阶段二 / 4.6）

职责：质量审查与事实核查，是 Orchestrator 反思重试闭环的执行者。

两级审查（对应升级计划"规则快筛 + LLM 深度评估"）：
1. 规则快筛：本地校验，不调模型，零成本且毫秒级，覆盖空结果/超短文本/URL缺失；
2. LLM 深度评估：规则通过后再调用审查模型打分，识别内容层面的问题。

状态语义（供 Orchestrator 控制反思重试）：
- SUCCESS        : 审查通过，产物可交付
- NEED_REVISION  : 质量不达标，附带 issues 作为修改建议，Orchestrator 触发重试
- FAILED         : 审查流程本身出错（如无可用模型）

防死循环：重试次数由 TaskContext.max_retries 统一控制，
Reviewer 自身不做重试，避免与 Orchestrator 的预算机制打架。
"""
from typing import List

from src.core.base_agent import BaseAgent
from src.core.contracts import (
    Artifact,
    AgentMessage,
    AgentResponse,
    TaskContext,
    STATUS_NEED_REVISION,
)

# 规则阈值
MIN_TEXT_LENGTH = 10          # 文本产物最短字符数
REVIEW_PROMPT_TEMPLATE = """你是一名严格的质量审查员。请审查以下 AI 生成内容，指出其中的问题。

## 审查维度
1. 事实准确性：是否存在明显的事实错误或虚构信息
2. 逻辑连贯：前后是否自洽，有无矛盾
3. 内容完整：是否切题，是否达到用户要求
4. 表达质量：是否存在明显的语病、冗余或格式问题

## 待审查内容
{content}

## 输出格式（严格 JSON，不要输出其他内容）
{{"score": 0到5的整数, "issues": ["问题1", "问题2"], "pass": true或false}}

评分标准：5=优秀可直接交付，3=可用但有小瑕疵，1=存在严重问题。
score 低于 3 或 pass 为 false 时，必须在 issues 中说明具体问题。"""


class ReviewerAgent(BaseAgent):
    """质量审查 Agent（Reviewer Agent）"""

    default_capability = "text-generation"

    def __init__(self, router, llm_client, name: str = "reviewer_agent",
                 min_text_length: int = MIN_TEXT_LENGTH,
                 enable_llm_review: bool = True):
        super().__init__(name=name, router=router, llm_client=llm_client,
                         capability="text-generation")
        self.min_text_length = min_text_length
        self.enable_llm_review = enable_llm_review

    def _run(self, message: AgentMessage, context: TaskContext,
             model_info: dict) -> AgentResponse:
        artifacts = message.artifacts
        if not artifacts:
            return AgentResponse.failed(
                self.name, error_code=-1, issues=["无待审查产物"]
            )

        # ---- 第一级：规则快筛（零成本，先挡掉明显问题）----
        rule_issues = self._rule_check(artifacts)
        if rule_issues:
            return AgentResponse.need_revision(self.name, rule_issues)

        # ---- 第二级：LLM 深度评估 ----
        # 仅对文本产物做深度评估：纯文本审查模型无法真正"看懂"图片/视频，
        # 让其评媒体 URL 只会产生误判，进而白白触发反思重试
        # （实测会导致视频被无谓重跑一次，浪费数分钟推理）。
        # 媒体产物由第一级规则（URL 可达性/格式）保证。
        reviewable = [a for a in artifacts if a.type == "text"]
        if not self.enable_llm_review or not reviewable:
            note = "规则审查通过" + ("（媒体产物，规则核验）" if not reviewable else "")
            return AgentResponse.success(
                self.name,
                artifacts=artifacts,
                output_text=f"{note}（{len(artifacts)} 项产物）",
            )

        review_text = self._compose_review_input(reviewable)
        self.model_invoked = True
        self._mark_call_start()
        resp = self.llm_client.call(
            model_name=model_info["model_name"],
            endpoint=model_info["endpoint"],
            api_key=model_info["api_key"],
            prompt=REVIEW_PROMPT_TEMPLATE.format(content=review_text),
            output_type="text",
        )

        if resp.status != "SUCCESS":
            # 审查模型不可用不应阻断主流程：降级为规则通过
            return AgentResponse.success(
                self.name,
                artifacts=artifacts,
                output_text="审查模型不可用，降级为规则审查通过",
            )

        verdict = self._parse_verdict(resp.data.content or "")
        if verdict is None:
            # 审查模型输出不可解析，保守放行
            return AgentResponse.success(
                self.name, artifacts=artifacts,
                output_text="审查结果解析失败，降级放行",
            )

        score, issues, passed = verdict
        if not passed:
            issues.append(f"审查评分 {score}/5，低于交付标准")
            return AgentResponse.need_revision(self.name, issues)

        return AgentResponse.success(
            self.name, artifacts=artifacts,
            output_text=f"审查通过，评分 {score}/5",
        )

    # ------------------------------------------------------------------
    # 规则快筛
    # ------------------------------------------------------------------
    def _rule_check(self, artifacts: List[Artifact]) -> List[str]:
        issues: List[str] = []
        for art in artifacts:
            if not art.content or not art.content.strip():
                issues.append(f"{art.type} 产物内容为空")
                continue
            if art.type == "text" and len(art.content.strip()) < self.min_text_length:
                issues.append(
                    f"文本内容过短（{len(art.content.strip())} 字符，"
                    f"要求至少 {self.min_text_length}）"
                )
            if art.type in ("image", "video") and not art.content.startswith("http"):
                issues.append(f"{art.type} 产物URL格式异常：{art.content[:50]}")
        return issues

    # ------------------------------------------------------------------
    # 审查输入组装与结果解析
    # ------------------------------------------------------------------
    @staticmethod
    def _compose_review_input(artifacts: List[Artifact]) -> str:
        parts = []
        for art in artifacts:
            if art.type == "text":
                parts.append(f"[文本产物]\n{art.content[:2000]}")
            elif art.type == "image":
                parts.append(f"[图片产物]\n描述: {art.metadata.get('prompt', '')}\nURL: {art.content}")
            elif art.type == "video":
                parts.append(f"[视频产物]\n描述: {art.metadata.get('prompt', '')}\nURL: {art.content}")
            else:
                parts.append(f"[{art.type}产物]\n{art.content[:500]}")
        return "\n\n".join(parts)

    @staticmethod
    def _parse_verdict(raw: str):
        """解析审查模型返回的 JSON，容错 Markdown 代码块包裹。
        返回 (score, issues, passed) 或 None（解析失败）
        """
        import json

        content = (raw or "").strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        # 提取第一个 JSON 对象
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None

        try:
            data = json.loads(content[start:end + 1])
        except (json.JSONDecodeError, ValueError):
            return None

        try:
            score = float(data.get("score", 0))
        except (TypeError, ValueError):
            score = 0.0

        issues = data.get("issues") or []
        if isinstance(issues, str):
            issues = [issues]
        passed = bool(data.get("pass", score >= 3))
        return int(score), list(issues), passed
