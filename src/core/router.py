from src.core.models import ModelInfo
from src.adapters.config import load_model_config

class Router:
    """路由器Router，根据能力匹配合适的模型"""
    def __init__(self):
        self.models = load_model_config()  # 从配置文件加载模型信息
        
    def get_model(self, capability_required: str, failed_models: list = None) -> dict:
        """
        根据所需能力和已失败模型列表，返回合适的模型信息

        输入:
            capability_required: 需要的能力标签，如 "text-generation"
            failed_models: 已经失败过的模型逻辑注册名列表，这些模型将被跳过

        返回:
            成功: {"model_name": "qwen-plus", "endpoint": "...", "api_key": "..."}
            失败: {"error": "NO_AVAILABLE_MODEL"}
        """
        if failed_models is None:
            failed_models = []

        candidates = [m for m in self.models if m.capability == capability_required]

        available = [m for m in candidates if m.registered_name not in failed_models]

        if available:
            model = available[0]  
            return {
                "model_name": model.model_name,
                "endpoint": model.endpoint,
                "api_key": model.api_key
                }
        
        return {"error": "NO_AVAILABLE_MODEL"}