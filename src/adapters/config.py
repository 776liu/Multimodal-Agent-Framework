import yaml
from pathlib import Path
from src.core.models import ModelInfo


def _load_config(config_path: str = None) -> dict:
    """加载模型配置文件，返回原始字典"""
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / "config" / "model.yaml"

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"模型配置文件未找到: {config_path}")
    except yaml.YAMLError as e:
        raise ValueError(f"模型配置文件格式错误: {e}")

def load_model_config(config_path: str = None) -> list[ModelInfo]:
    """从 YAML 配置文件加载模型注册信息"""
    config = _load_config(config_path) if config_path else _load_config()

    models = []
    for item in config["models"]:
        models.append(ModelInfo(
            registered_name=item["registered_name"],
            model_name=item["model_name"],
            endpoint=item["endpoint"],
            api_key=item["api_key"],
            capability=item["capability"]
        ))
    return models


def load_app_config(config_path: str = None) -> dict:
    """从 config/app.yaml 加载前端应用参数"""
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / "config" / "app.yaml"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        # 配置文件不存在，用模板文件或默认值
        example_path = Path(__file__).parent.parent.parent / "config" / "app.example.yaml"
        if example_path.exists():
            with open(example_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
        else:
            config = {}
    app = config.get("app", {}) if config else {}
    return {
        "api_base": app.get("api_base", "http://127.0.0.1:8100"),
        "poll_interval": app.get("poll_interval", 2),
        # 视频生成任务耗时约 5-6 分钟，默认超时放宽到 15 分钟避免误杀
        "timeout_seconds": app.get("timeout_seconds", 900),
        "video_poll_budget": app.get("video_poll_budget", 600),
        "video_poll_interval": app.get("video_poll_interval", 6),
    }


def load_reviewer_config(config_path: str = None) -> dict:
    """加载 Reviewer 严格度配置（工单 T-04）

    独立成函数便于论文实验做参数对比：只改 yaml、重启服务即可切换严格度，
    无需改代码。三级分级的阈值语义见 ReviewerAgent 类文档。
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / "config" / "app.yaml"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        example_path = Path(__file__).parent.parent.parent / "config" / "app.example.yaml"
        if example_path.exists():
            with open(example_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
        else:
            config = {}
    reviewer = (config or {}).get("reviewer", {}) or {}
    return {
        # >= 该分值：通过，不记警告
        "pass_threshold": int(reviewer.get("pass_threshold", 4)),
        # >= 该分值但 < pass_threshold：通过但记 warning（可交付，不触发重试）
        "warn_threshold": int(reviewer.get("warn_threshold", 3)),
        # 是否启用 LLM 深度评估（关闭后仅规则快筛，零 Token 成本）
        "enable_llm_review": bool(reviewer.get("enable_llm_review", True)),
        # 文本产物最短字符数（规则快筛）
        "min_text_length": int(reviewer.get("min_text_length", 10)),
    }