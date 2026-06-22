from src.core.models import ModelInfo
from src.adapters.config import load_model_config

class Router:
    """路由器Router，根据能力匹配合适的模型"""
    def __init__(self):
        self.models = load_model_config()  # 从配置文件加载模型信息

    def list_models(self) -> list[dict]:
        """返回所有注册模型的基本信息列表"""
        return [
            {
                "registered_name": m.registered_name,
                "model_name": m.model_name,
                "capability": m.capability
            }
            for m in self.models
        ]
        
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
    
    # 临时方案：在 router.py 里加一个脱敏函数
    def _mask_key(key: str) -> str:
        if len(key) > 10:
            return key[:6] + "****" + key[-4:]
        return "****"
    
    # 在 get_model 返回前对 api_key 脱敏（仅用于调试输出，实际给 LLMClient 的是未脱敏的原始 Key）