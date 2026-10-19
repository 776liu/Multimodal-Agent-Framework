import json
from src.core.router import Router
from src.core.llm_client import LLMClient
from src.core.models import ExecutionPlan, Subtask
import uuid

SYSTEM_PROMPT = """你是一个任务拆解专家。你的职责是分析用户输入，判断任务意图，并将复杂任务拆解为有序的子任务列表。

## 意图类型
- single_text: 单一文本任务（翻译、问答、摘要等纯文本输入→纯文本输出）
- single_multimodal: 单一多模态生成任务（生成图片、视频等）
- multi_step_multimodal: 多步骤多模态任务（需要先后执行多个不同能力的子任务）

## capability 标签白名单（每个子任务的 capability 只能从以下标签中选择，禁止发明其他标签）
- text-generation: 纯文本生成（写作、翻译、摘要、文案、问答、脚本创作等）。理解图片后的写作也归入此类。
- image-generation: 生成图片（文生图）
- image-to-text: 理解/描述一张已存在的图片（看图说话、图生文）
- video-generation: 生成视频（文生视频、图生视频。注意：视频生成耗时较长约5分钟）

## 引用前序产物的规则
- 后续步骤需要用到前面步骤的输出时，必须填写 reference_step 指向对应步骤号
- reference_step 为 0 表示引用对话历史中的图片（上一轮任务生成的图）
- 需要基于图片写作时，直接用带图输入的 text-generation（系统会自动路由到视觉模型），不要为"理解图片"单独造步骤
- 用户要"视频/短片/动画/分镜视频"时，用 video-generation；不需要先单独拆出生成图片的步骤，系统会自动按参考图选择文生视频或图生视频

## 输出格式
你必须严格输出以下JSON格式，不要输出任何其他内容：
{
    "intent": "single_text",
    "subtasks": [
        {"step": 1, "capability": "...", 
        "prompt": "...", 
        "image_url": "...", # 可选，需要图片输入时填写
        "reference_step": 2 # 可选，引用前面步骤的输出时填写
        }
    ]
}

## 示例
用户输入: "把Hello World翻译成中文"
输出: {"intent": "single_text", "subtasks": [{"step": 1, "capability": "text-generation", "prompt": "把Hello World翻译成中文"}]}

用户输入: "生成一张关于未来城市的图片"
输出: {"intent": "single_multimodal", "subtasks": [{"step": 1, "capability": "image-generation", "prompt": "未来城市的图片"}]}

用户输入: "生成一张未来城市的图片，并写一段描述"
输出: 
    {
    "intent": "multi_step_multimodal",
    "subtasks": [
    {step": 1, "capability": "image-generation", "prompt": "未来城市的图片"},
    {"step": 2, "capability": "text-generation", "prompt": "描述这张图片", "reference_step": 1}
    ]}

用户输入: "为这张图片生成脚本文案"（上下文包含前序图片）
输出:
    {
    "intent": "multi_step_multimodal",
    "subtasks": [
    {"step": 1, "capability": "text-generation", "prompt": "为这张图片生成脚本文案", "reference_step": 0}
    ]}
    （注: reference_step 为 0 表示引用对话历史中的图片，无需单独的理解步骤）

用户输入: "生成一段5秒的视频：城市夜晚的霓虹街道，镜头缓慢推进"
输出: {"intent": "single_multimodal", "subtasks": [{"step": 1, "capability": "video-generation", "prompt": "城市夜晚的霓虹街道，镜头缓慢推进"}]}

用户输入: "把这个画面做成一段动态短片，并配一段旁白"
输出:
    {
    "intent": "multi_step_multimodal",
    "subtasks": [
    {"step": 1, "capability": "video-generation", "prompt": "让这张图片动起来，画面自然延展", "reference_step": 0},
    {"step": 2, "capability": "text-generation", "prompt": "为这段视频写一段旁白", "reference_step": 1}
    ]}

现在，请分析以下用户输入："""


class TaskRouter:
    """任务拆解"""

    def __init__(self, router: Router , llm_client: LLMClient):
        self.router = router
        self.llm_client = llm_client

    def route_task(self, user_input: str) -> ExecutionPlan:
        """
        拆解意图
        """

        model_info = self.router.get_model("text-generation")

        full_prompt = SYSTEM_PROMPT + user_input

        response = self.llm_client.call(
            model_name = model_info["model_name"],
            endpoint = model_info["endpoint"],
            api_key = model_info["api_key"],
            prompt = full_prompt,
            output_type = "text"
        )

        if response.status == "SUCCESS" :
            try:
                # 容错解析：模型有时会用 ```json ... ``` 代码块包裹 JSON，
                # 剥掉 Markdown 围栏后再解析
                content = response.data.content.strip()
                if content.startswith("```"):
                    content = content.split("```")[1]
                    if content.startswith("json"):
                        content = content[4:]
                    content = content.strip()
                data = json.loads(content)
                subtasks = [Subtask(**s) for s in data["subtasks"]]
                return ExecutionPlan(
                    intent = data["intent"],
                    task_id = "task_" + uuid.uuid4().hex,
                    subtasks = subtasks
                )
            except (json.JSONDecodeError, KeyError) as e:
                return ExecutionPlan(
                    intent = "error",
                    task_id = "task_" + uuid.uuid4().hex,
                    subtasks = []
                )