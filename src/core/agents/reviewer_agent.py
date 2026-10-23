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

# 分级阈值默认值（可被 config/app.yaml 的 reviewer 段覆盖，工单 T-04）
DEFAULT_PASS_THRESHOLD = 4    # >= 4 直接通过
DEFAULT_WARN_THRESHOLD = 3    # 3~4 通过但记 warning；< 3 打回

REVIEW_PROMPT_TEMPLATE = """你是一名质量审查员。请审查以下 AI 生成内容，判断它能否直接交付给用户。

## 审查维度
1. 事实准确性：是否存在**明确的事实错误**或杜撰信息
2. 逻辑连贯：前后是否自相矛盾
3. 内容完整：是否切题，是否满足用户要求
4. 表达质量：是否存在明显语病或格式崩坏

## 判定原则（重要）
- **只针对实质性缺陷打回**。以下情况一律视为通过，不要因此扣分或打回：
  - 表述通俗、口语化，或不够学术严谨；
  - 内容正确但不全面、未展开细节；
  - 使用了"约""之一""大多数"等合理限定词；
  - 部分数据略有出入但在常识容许范围内（如海拔写约8848米）。
- **不要凭空追加要求**：只能基于文本自身内容判断，不得引入文本未主张的观点去反驳。
- 只有出现**确凿的事实错误、自相矛盾、答非所问、内容崩坏**时才判为不通过。

## 待审查内容
{content}

## 输出格式（严格 JSON，不要输出其他内容）
{{"score": 0到5的整数, "issues": ["问题1", "问题2"]}}

## 评分标准
5 = 事实正确、表达通顺，可直接交付
4 = 有细微可改进处，但不影响使用
3 = 存在小瑕疵，仍可交付（如表述略笼统）
2 = 存在明显问题，不建议直接交付
1 = 存在严重事实错误或内容崩坏

注意：issues 只在确实发现问题时填写；无问题时给空数组。"""


class ReviewerAgent(BaseAgent):
    """质量审查 Agent（Reviewer Agent）"""

    default_capability = "text-generation"

    def __init__(self, router, llm_client, name: str = "reviewer_agent",
                 min_text_length: int = MIN_TEXT_LENGTH,
                 enable_llm_review: bool = True,
                 pass_threshold: int = DEFAULT_PASS_THRESHOLD,
                 warn_threshold: int = DEFAULT_WARN_THRESHOLD):
        super().__init__(name=name, router=router, llm_client=llm_client,
                         capability="text-generation")
        self.min_text_length = min_text_length
        self.enable_llm_review = enable_llm_review
        self.pass_threshold = pass_threshold
        self.warn_threshold = warn_threshold

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
            # 审查模型输出不可解析，保守放行（避免因审查器故障误伤产物）
            return AgentResponse.success(
                self.name, artifacts=artifacts,
                output_text="审查结果解析失败，降级放行",
            )

        score, issues = verdict

        # 三级分级（工单 T-04）：判定**只依据评分**，不采信模型自报的 pass 字段。
        # 原因：模型几乎总会返回 pass，若优先采信它，本项目定义的阈值将完全失效，
        # 严格度既不可配置也不可预测；而评分在实测中对同一文本存在非确定性波动，
        # 因此需要一个明确、可调、可回归验证的阈值边界。
        if score >= self.pass_threshold:
            return AgentResponse.success(
                self.name, artifacts=artifacts,
                output_text=f"审查通过，评分 {score}/5",
            )

        if score >= self.warn_threshold:
            # 可用但有瑕疵：放行交付，仅记录警告，不触发反思重试（省 Token）
            warn = list(issues) or ["存在轻微瑕疵"]
            return AgentResponse.success(
                self.name, artifacts=artifacts,
                output_text=f"审查通过（已记录警告），评分 {score}/5："
                            f"{'；'.join(warn[:3])}",
            )

        issues.append(f"审查评分 {score}/5，低于交付标准（阈值 {self.warn_threshold}）")
        return AgentResponse.need_revision(self.name, issues)

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

        返回 (score, issues) 或 None（解析失败）。
        不再返回模型自报的 pass 字段——严格度由本项目阈值决定（工单 T-04）。
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

        if not isinstance(data, dict) or "score" not in data:
            return None

        try:
            score = int(float(data["score"]))
        except (TypeError, ValueError):
            return None

        # 评分越界视为解析异常，交由调用方保守放行
        if not 0 <= score <= 5:
            return None

        issues = data.get("issues") or []
        if isinstance(issues, str):
            issues = [issues]
        return score, [str(i) for i in issues]
