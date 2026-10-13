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
        output_type: str,
        image_url: str = ""
    ) -> LLMResponse:
        """
        调用大模型 API,返回标准化响应。
        统一请求格式

        输入: model_name, endpoint, api_key, prompt, output_type
        输出: LLMResponse 对象
        """
        if output_type == "text":
            url = endpoint
            if image_url :
                payload = {
                    "model": model_name,
                    "messages": [{"role": "user", "content": [
                        {"type": "text","text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}}
                    ]}]
                }
            else:
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
            url = endpoint
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            if "images/generations" in endpoint:
                # OpenAI Images 兼容协议 (硅基流动等)：
                # POST {prompt, image_size}, 响应 {"images": [{"url": "..."}]}
                payload = {
                    "model": model_name,
                    "prompt": prompt,
                    "image_size": "1024x1024"
                }
                timeout = 60
                response_style = "openai_images"
            else:
                # DashScope 原生异步接口的同步模式 (阿里云百炼)：
                # payload 有 input 包装, 响应有 output 前缀
                if image_url:
                    # 图生图模式：只传参考图，不混用 text
                    payload = {"model": model_name,
                        "input": {
                            "messages": [
                                {
                                    "role": "user",
                                    "content": [{"image": image_url}]
                                }
                            ]
                        },
                        "parameters": {
                            "n": 1,
                            "watermark": False
                        }
                    }
                else:
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
                timeout = 300
                response_style = "dashscope"
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
            if response_style == "openai_images":
                # OpenAI Images 兼容协议响应：{"images": [{"url": "..."}]}
                image_url = data["images"][0]["url"]
            else:
                # DashScope 原生响应：output.choices[0].message.content[0].image
                image_url = data["output"]["choices"][0]["message"]["content"][0]["image"]
            return LLMResponse(
                status="SUCCESS",
                data=TaskResult(type="image", url=image_url),
                model_name=model_name
            )
