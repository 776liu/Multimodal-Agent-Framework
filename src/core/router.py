from src.core.models import ModelInfo
from src.adapters.config import load_model_config

# 能力标签别名表：TaskRouter(大模型)可能输出近义/发明标签，
# 路由时先按原标签查，查不到再按别名归一化到已注册标签
CAPABILITY_ALIASES = {
    "image-understanding": "image-to-text",   # 理解图片 ≈ 看图说话
    "image-caption": "image-to-text",
    "image-analysis": "image-to-text",
    "vision": "image-to-text",
    "text-generation-vlm": "image-to-text",
    "image-to-image": "image-generation",
    "text2image": "image-generation",
    "video-generation": "image-generation",   # 无视频模型时暂由生图兜底
    "script-writing": "text-generation",
    "copywriting": "text-generation",
    "translation": "text-generation",
    "summarization": "text-generation",
}

class Router:
    """路由器Router,根据能力匹配合适的模型"""

    # 类级缓存：最近一次加载的注册能力集合（供 _normalize_capability 查询）
    _registered_capabilities: list = []

    def __init__(self, models: list[ModelInfo] = None):
        self.models = models if models is not None else load_model_config()
        Router._registered_capabilities = self.models
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

        # 标签归一化：原标签查不到注册模型时，尝试别名映射
        capability_required = self._normalize_capability(capability_required)

        candidates = [m for m in self.models if m.capability == capability_required]

        available = [m for m in candidates if m.registered_name not in failed_models]

        # 按物理模型去重：多个注册名可指向同一个 model_name（如同一模型配置
        # 主备两条），失败黑名单按物理模型生效，避免同一模型被重复重试
        tried_physical = {
            c.model_name for c in candidates
            if c.registered_name in failed_models
        }
        available = [m for m in available if m.model_name not in tried_physical]

        if available:
            model = available[0]
            return {
                "registered_name": model.registered_name,
                "model_name": model.model_name,
                "endpoint": model.endpoint,
                "api_key": model.api_key,
                # 标记是否经由别名归一化命中（供观测与语义化报错参考）
                "resolved_capability": capability_required,
                }

        return {"error": "NO_AVAILABLE_MODEL", "capability": capability_required}

    @staticmethod
    def _normalize_capability(capability: str) -> str:
        """能力标签归一化：注册表中存在原标签则原样返回，否则尝试别名映射"""
        registered = {m.capability for m in Router._registered_capabilities}
        if capability in registered:
            return capability
        return CAPABILITY_ALIASES.get(capability, capability)
    
    # 临时方案：在 router.py 里加一个脱敏函数
    def _mask_key(key: str) -> str:
        if len(key) > 10:
            return key[:6] + "****" + key[-4:]
        return "****"
    
    # 在 get_model 返回前对 api_key 脱敏（仅用于调试输出，实际给 LLMClient 的是未脱敏的原始 Key）