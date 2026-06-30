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
        "api_base": app.get("api_base", "http://127.0.0.1:8000"),
        "poll_interval": app.get("poll_interval", 2),
        "timeout_seconds": app.get("timeout_seconds", 180),
    }