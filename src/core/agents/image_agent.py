"""Image Agent（升级计划 阶段二）

职责：文生图（text-to-image）与图生图（image-to-image）。

关键设计：
- 继承阶段一的 BaseAgent，只实现 _run；
- 图生图时把上游图片 URL 透传给 LLMClient，由其按平台协议组装请求；
- 产物：Artifact(image)，携带 prompt 与参考图信息，供下游（如 Video Agent）复用。
"""
from src.core.base_agent import BaseAgent
from src.core.contracts import (
    Artifact,
    AgentMessage,
    AgentResponse,
    TaskContext,
    ARTIFACT_IMAGE,
)


class ImageAgent(BaseAgent):
    """图像生成 Agent（Image Agent）"""

    default_capability = "image-generation"

    def __init__(self, router, llm_client, name: str = "image_agent"):
        super().__init__(name=name, router=router, llm_client=llm_client,
                         capability="image-generation")

    def _run(self, message: AgentMessage, context: TaskContext,
             model_info: dict) -> AgentResponse:
        # 有上游图片则走图生图，否则文生图
        ref_image = message.first_image_url

        resp = self.llm_client.call(
            model_name=model_info["model_name"],
            endpoint=model_info["endpoint"],
            api_key=model_info["api_key"],
            prompt=message.prompt,
            output_type="image",
            image_url=ref_image,
        )

        if resp.status != "SUCCESS":
            return AgentResponse.failed(
                self.name,
                error_code=resp.error_code,
                issues=[f"图像生成失败(错误码 {resp.error_code})"],
            )

        url = resp.data.url if resp.data else None
        if not url:
            return AgentResponse.failed(
                self.name, error_code=-1, issues=["模型未返回图片URL"]
            )

        artifact = Artifact.image_of(
            url,
            step=message.step,
            model=model_info["model_name"],
            prompt=message.prompt,
            mode="image-to-image" if ref_image else "text-to-image",
            reference_image=ref_image or "",
        )

        return AgentResponse.success(self.name, artifacts=[artifact])
