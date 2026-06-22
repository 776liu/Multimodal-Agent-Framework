import yaml
from pathlib import Path
from src.core.models import ModelInfo


def load_model_config() -> list[ModelInfo]:
    """从 YAML 配置文件加载模型注册信息"""
    config_path = Path(__file__).parent.parent.parent / "config" / "model.yaml"

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

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