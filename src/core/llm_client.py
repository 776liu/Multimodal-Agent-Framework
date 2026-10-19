import requests
import time
from src.core.models import LLMResponse, TaskResult


class LLMClient:
    """封装 HTTP 调用，只负责请求/响应/超时"""

    # ---- 视频生成异步任务参数（硅基流动 /v1/video/submit + /v1/video/status）----
    # 平台实测：Wan2.2 队列约 2 分钟 + 推理约 3.5 分钟，总计 ~5.5 分钟
    VIDEO_SUBMIT_TIMEOUT = 60        # 提交阶段最多等 60s
    VIDEO_POLL_INTERVAL = 6          # 轮询间隔 6s，避免过度频繁请求
    VIDEO_POLL_BUDGET = 600          # 总预算 10 分钟，超时即放弃（留足余量且不无限等）
    VIDEO_PROGRESS_TTL = 900         # 视频进度记录存活时间，供前端查询
    _video_progress: dict = {}       # requestId -> 进度快照（供 SSE/前端展示）

    @classmethod
    def get_video_progress(cls, request_id: str) -> dict:
        """查询视频生成进度快照（供前端轮询展示：排队位置/状态）"""
        return cls._video_progress.get(request_id, {})

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
        elif output_type == "video":
            # 异步任务协议（提交 + 轮询），单独走 _call_video 分支
            return self._call_video(
                model_name=model_name,
                endpoint=endpoint,
                api_key=api_key,
                prompt=prompt,
                image_url=image_url,
            )
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

    # ------------------------------------------------------------------
    # 视频生成分支：异步提交 + 轮询状态
    # 协议（硅基流动）:
    #   POST {base}/v1/video/submit  {model, prompt, [image]} -> {requestId}
    #   POST {base}/v1/video/status  {requestId}              -> {status, results}
    #   status ∈ InQueue / InProgress / Succeed / Failed
    # ------------------------------------------------------------------
    def _call_video(
        self,
        model_name: str,
        endpoint: str,
        api_key: str,
        prompt: str,
        image_url: str = "",
    ) -> LLMResponse:
        """视频生成：提交异步任务并轮询直至终态。

        超时策略：总预算 VIDEO_POLL_BUDGET(10min)，
        超时返回 408(可重试) 而非无限等待；平台侧 Failed 立即返回失败。
        """
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        # 由 endpoint 推导同源的状态查询端点（endpoint 形如 .../v1/video/submit）
        base = endpoint.rsplit("/submit", 1)[0] if "/submit" in endpoint else endpoint
        status_url = f"{base}/status"

        # ---- Step 1: 提交任务 ----
        submit_payload = {"model": model_name, "prompt": prompt}
        if image_url:
            # 图生视频：首帧参考图（I2V 模型支持）
            submit_payload["image"] = image_url

        try:
            resp = requests.post(endpoint, json=submit_payload, headers=headers,
                                 timeout=self.VIDEO_SUBMIT_TIMEOUT)
        except requests.exceptions.Timeout:
            return LLMResponse(status="FAILED", error_code=408, model_name=model_name)
        except requests.exceptions.ConnectionError:
            return LLMResponse(status="FAILED", error_code=503, model_name=model_name)

        if resp.status_code != 200:
            print(f"[DEBUG] 视频提交响应体: {resp.text}")
            return LLMResponse(status="FAILED", error_code=resp.status_code, model_name=model_name)

        try:
            request_id = resp.json().get("requestId")
        except ValueError:
            return LLMResponse(status="FAILED", error_code=-1, model_name=model_name)

        if not request_id:
            return LLMResponse(status="FAILED", error_code=-1, model_name=model_name)

        # ---- Step 2: 轮询状态直至终态 ----
        deadline = time.time() + self.VIDEO_POLL_BUDGET
        poll_count = 0

        while time.time() < deadline:
            time.sleep(self.VIDEO_POLL_INTERVAL)
            poll_count += 1

            try:
                sresp = requests.post(status_url, json={"requestId": request_id},
                                      headers=headers, timeout=30)
            except requests.exceptions.Timeout:
                # 单次轮询超时不算失败，继续等到预算耗尽
                continue
            except requests.exceptions.ConnectionError:
                return LLMResponse(status="FAILED", error_code=503, model_name=model_name)

            if sresp.status_code != 200:
                # 轮询偶发错误（如限流）可容忍，继续重试
                if poll_count % 5 == 0:
                    print(f"[DEBUG] 视频状态查询异常 {sresp.status_code}: {sresp.text[:120]}")
                continue

            data = sresp.json()
            status = data.get("status")

            # 记录进度快照（供前端展示排队/生成中状态）
            self._video_progress[request_id] = {
                "request_id": request_id,
                "status": status,
                "position": data.get("position"),
                "elapsed_polls": poll_count,
                "budget_remaining": max(0, int(deadline - time.time())),
                "model_name": model_name,
                "updated_at": time.time(),
            }

            if status == "Succeed":
                videos = (data.get("results") or {}).get("videos") or []
                if not videos or not videos[0].get("url"):
                    return LLMResponse(status="FAILED", error_code=-1, model_name=model_name)
                video_url = videos[0]["url"]
                return LLMResponse(
                    status="SUCCESS",
                    data=TaskResult(type="video", url=video_url),
                    model_name=model_name
                )

            if status == "Failed":
                reason = data.get("reason") or "video generation failed"
                print(f"[DEBUG] 视频生成失败: {reason}")
                return LLMResponse(status="FAILED", error_code=500, model_name=model_name)

            # InQueue / InProgress: 继续轮询

        # 预算耗尽：返回可重试的超时错误，不无限等待
        print(f"[DEBUG] 视频生成超时: 轮询 {poll_count} 次仍未完成（预算 {self.VIDEO_POLL_BUDGET}s）")
        return LLMResponse(status="FAILED", error_code=408, model_name=model_name)
