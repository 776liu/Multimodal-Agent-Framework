"""Video Agent（升级计划 阶段三配套 / 论文主线能力）

职责：文生视频（T2V）与图生视频（I2V）。

之所以单独成 Agent 而不塞进 ImageAgent：
1. 耗时量级不同（视频 3-6 分钟 vs 图片 5 秒），需要独立的进度语义与超时预算；
2. 论文中它是多 Agent 分工最有说服力的例子——不同 Agent 承担不同
   时间尺度的任务，编排器必须异步协调；
3. 输入契约不同（T2V 只有 prompt，I2V 需要首帧图）。

产物：Artifact(video)，携带 prompt 与首帧信息，供 Reviewer 校验与前端渲染。
"""
from src.core.base_agent import BaseAgent
from src.core.prompt_policy import apply_no_text
from src.core.contracts import (
    Artifact,
    AgentMessage,
    AgentResponse,
    TaskContext,
)


class VideoAgent(BaseAgent):
    """视频生成 Agent（Video Agent）"""

    default_capability = "video-generation"

    def __init__(self, router, llm_client, name: str = "video_agent"):
        super().__init__(name=name, router=router, llm_client=llm_client,
                         capability="video-generation")

    def resolve_capability(self, message: AgentMessage) -> str:
        """有首帧参考图时走图生视频模型池"""
        if message.first_image_url:
            return "image-to-video"
        return self.capability

    def _run(self, message: AgentMessage, context: TaskContext,
             model_info: dict) -> AgentResponse:
        ref_image = message.first_image_url
        # 压制模型自发的伪文字/水印（模型固有缺陷，prompt 层面规避）
        prompt = apply_no_text(message.prompt, is_video=True)

        # 视频为异步长任务，LLMClient 内部已实现提交+轮询与超时预算
        self.model_invoked = True
        self._mark_call_start()
        resp = self.llm_client.call(
            model_name=model_info["model_name"],
            endpoint=model_info["endpoint"],
            api_key=model_info["api_key"],
            prompt=prompt,
            output_type="video",
            image_url=ref_image,
        )

        if resp.status != "SUCCESS":
            return AgentResponse.failed(
                self.name,
                error_code=resp.error_code,
                issues=[f"视频生成失败(错误码 {resp.error_code})"],
            )

        url = resp.data.url if resp.data else None
        if not url:
            return AgentResponse.failed(
                self.name, error_code=-1, issues=["模型未返回视频URL"]
            )

        artifact = Artifact.video_of(
            url,
            step=message.step,
            model=model_info["model_name"],
            prompt=prompt,
            mode="image-to-video" if ref_image else "text-to-video",
            first_frame=ref_image or "",
        )
        return AgentResponse.success(self.name, artifacts=[artifact])
