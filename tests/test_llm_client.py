from src.core.router import Router
from src.core.llm_client import LLMClient


def test_text_generation():
    print("=" * 50)
    print("测试1: 文本生成 (text-generation)")
    print("=" * 50)

    router = Router()
    model_info = router.get_model("text-generation")

    if "error" in model_info:
        print(f"❌ Router 获取模型失败: {model_info['error']}")
        return

    print(f"模型: {model_info['model_name']}")

    client = LLMClient()
    response = client.call(
        model_name=model_info["model_name"],
        endpoint=model_info["endpoint"],
        api_key=model_info["api_key"],
        prompt="你好，请用一句话介绍你自己。",
        output_type="text"
    )

    if response.status == "SUCCESS":
        print(f"✅ 文本生成成功")
        print(f"内容: {response.data.content}")
    else:
        print(f"❌ 文本生成失败")
        print(f"错误码: {response.error_code}")

    return response


def test_image_generation():
    print("\n" + "=" * 50)
    print("测试2: 图片生成 (image-generation)")
    print("=" * 50)

    router = Router()
    model_info = router.get_model("image-generation")

    if "error" in model_info:
        print(f"❌ Router 获取模型失败: {model_info['error']}")
        return

    print(f"模型: {model_info['model_name']}")

    client = LLMClient()
    response = client.call(
        model_name=model_info["model_name"],
        endpoint=model_info["endpoint"],
        api_key=model_info["api_key"],
        prompt="一只在夕阳下奔跑的柴犬",
        output_type="image"
    )

    if response.status == "SUCCESS":
        print(f"✅ 图片生成成功")
        print(f"图片URL: {response.data.url}")
        print(f"（请手动复制URL到浏览器查看图片）")
    else:
        print(f"❌ 图片生成失败")
        print(f"错误码: {response.error_code}")

    return response


if __name__ == "__main__":
    test_text_generation()
    test_image_generation()