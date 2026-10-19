"""Writer Agent（升级计划 阶段二）

职责：文本生成、翻译、摘要、文案撰写、脚本创作。

关键设计：
- 继承阶段一的 BaseAgent，只实现 _run，路由/重试/调用链由基类托管；
- 视觉路由：消息中携带图片时，自动改用 image-to-text 标签走 VLM 模型池，
  避免把图片喂给纯文本模型（平台会返回 20041 not a VLM）；
- 产物：统一包装为 Artifact(text)，可直接传给下游步骤。
"""
from typing import Optional

from src.core.base_agent import BaseAgent
from src.core.contracts import (
    Artifact,
    AgentMessage,
    AgentResponse,
    TaskContext,
    ARTIFACT_IMAGE,
)


class WriterAgent(BaseAgent):
    """文本创作 Agent（Writer Agent）"""

    default_capability = "text-generation"

    def __init__(self, router, llm_client, name: str = "writer_agent"):
        super().__init__(name=name, router=router, llm_client=llm_client,
                         capability="text-generation")

    def resolve_capability(self, message: AgentMessage) -> str:
        """带图输入时走视觉模型池，否则用纯文本池"""
        if message.first_image_url:
            return "image-to-text"
        return self.capability

    def _run(self, message: AgentMessage, context: TaskContext,
             model_info: dict) -> AgentResponse:
        image_url = message.first_image_url

        resp = self.llm_client.call(
            model_name=model_info["model_name"],
            endpoint=model_info["endpoint"],
            api_key=model_info["api_key"],
            prompt=message.prompt,
            output_type="text",
            image_url=image_url,
        )

        if resp.status != "SUCCESS":
            return AgentResponse.failed(
                self.name,
                error_code=resp.error_code,
                issues=[f"文本生成失败(错误码 {resp.error_code})"],
            )

        content = (resp.data.content or "").strip()
        if not content:
            return AgentResponse.failed(
                self.name, error_code=-1, issues=["模型返回空内容"]
            )

        # 产物：文本 Artifact，附带来源信息便于下游溯源
        artifact = Artifact.text_of(
            content,
            step=message.step,
            model=model_info["model_name"],
            used_vision=bool(image_url),
        )

        # 上游图片作为上下文保留，便于下游回溯（图生文场景）
        upstream = [a for a in message.artifacts if a.type == ARTIFACT_IMAGE]

        return AgentResponse.success(
            self.name,
            artifacts=[artifact] + upstream,
            output_text=content,
        )
