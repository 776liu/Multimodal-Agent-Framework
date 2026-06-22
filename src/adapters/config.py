import yaml
from pathlib import Path
from src.core.models import ModelInfo


def load_model_config() -> list[ModelInfo]:
    """从 YAML 配置文件加载模型注册信息"""
    config_path = Path(__file__).parent.parent.parent / "config" / "model.yaml"

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"模型配置文件未找到: {config_path}")
    except yaml.YAMLError as e:
        raise ValueError(f"模型配置文件格式错误: {e}")

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