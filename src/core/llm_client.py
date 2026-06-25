import requests
from src.core.models import LLMResponse, TaskResult


class LLMClient:
    """封装 HTTP 调用，只负责请求/响应/超时"""

    def call(
        self,
        model_name: str,
        endpoint: str,
        api_key: str,
        prompt: str,
        output_type: str
    ) -> LLMResponse:
        """
        调用大模型 API，返回标准化响应。

        输入: model_name, endpoint, api_key, prompt, output_type
        输出: LLMResponse 对象
        """
        if output_type == "text":
            url = endpoint
            payload = {
                "model": model_name,
                "messages": [{"role": "user", "content": prompt}]
            }
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            timeout = 60
        elif output_type == "image":
            # 原生 API 同步模式：payload 有 input 包装，timeout 拉大
            url = endpoint
            payload = {
                "model": model_name,
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"text": prompt}]
                        }
                    ]
                },
                "parameters": {
                    "n": 1,
                    "watermark": False
                }
            }
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            timeout = 300
        else:
            return LLMResponse(
                status="FAILED",
                error_code=-1,
                model_name=model_name
            )

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)
        except requests.exceptions.Timeout:
            return LLMResponse(
                status="FAILED",
                error_code=408,
                model_name=model_name
            )
        except requests.exceptions.ConnectionError:
            return LLMResponse(
                status="FAILED",
                error_code=503,
                model_name=model_name
            )

        if response.status_code != 200:
            print(f"[DEBUG] 响应体: {response.text}")
            return LLMResponse(
                status="FAILED",
                error_code=response.status_code,
                model_name=model_name
            )

        data = response.json()

        if output_type == "text":
            # 兼容模式响应：无 output 前缀
            content = data["choices"][0]["message"]["content"]
            return LLMResponse(
                status="SUCCESS",
                data=TaskResult(type="text", content=content),
                model_name=model_name
            )

        elif output_type == "image":
            # 原生 API 响应：有 output 前缀
            image_url = data["output"]["choices"][0]["message"]["content"][0]["image"]
            return LLMResponse(
                status="SUCCESS",
                data=TaskResult(type="image", url=image_url),
                model_name=model_name
            )
