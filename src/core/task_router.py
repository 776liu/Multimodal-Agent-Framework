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
                data = json.loads(response.data.content)
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