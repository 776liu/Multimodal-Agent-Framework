from src.core.models import BuilderInput, BuilderOutput
import time
import json
import os

class Builder:

    def __init__(self, storage = None):
        self.storage = storage

    def build(self, input: BuilderInput) -> dict:
        """拼装前端响应和后端日志"""

        if input.final_status == "SUCCESS":            
            data = {
                "results" : [{"type": r.type, "url": r.url, "content": r.content} for r in input.results]
            }

        elif input.final_status == "PARTIAL_SUCCESS":
            successful = [r for r in input.results if r.content or r.url]
            data = {
                "results" : [{"type": r.type, "url": r.url, "content": r.content}for r in successful]
            }
        
        else:
            data = {
                "type" : "text",
                "message" : "服务暂时不可用，请稍后重试"
            }
        
        frontend = {
            "task_id" : input.task_id,
            "task_status" : input.final_status,
            "system_status" : "READY",
            "data" : data
        }

        log = {
            "task_id" : input.task_id,
            "timestamp" : str(time.time()),
            "task_status" : input.final_status,
            "system_status" : "READY",
            "call_chain" :[
                {
                    "model_name" : c.model_name,
                    "capability" : c.capability,
                    "status" : c.status,
                    "error_code" : c.error_code,
                    "attempted_at" : c.attempted_at
                }
                for c in input.call_chain
            ],
            "error_summary" :[
                {
                    "model_name" : c.model_name,
                    "capability" : c.capability,
                    "error_code" : c.error_code
                }
                for c in input.call_chain if c.status == "FAILED"
            ]
        }

        os.makedirs("logs", exist_ok=True)
        with open(f"logs/{input.task_id}.json", "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)

        if self.storage:
            self.storage.save_task_log(
                task_id = input.task_id,
                session_id = getattr(input, "session_id", "default"),
                frontend = frontend,
                log = log
            )
        

        return {
            "frontend_response" : frontend,
            "log_record" : log
        }

