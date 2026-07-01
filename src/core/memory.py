from typing import List,Dict
from src.core.models import Messages
import json


class Memory:
    """会话记忆，存储和检索历史对话"""
    def __init__(self, max_history: int = 10, storage = None):
        self.max_history = max_history
        self.storage = storage
        self.sessions: Dict[str, List[Messages]] = {}


    def add(self, session_id: str, role: str, content: str) ->None:
        """添加一条消息到会话"""

        if self.storage:
            self.storage.save_message(session_id, role, content)

        if session_id not in self.sessions:
            self.sessions[session_id] = []
        self.sessions[session_id].append(Messages(role=role, content=content))

        max_messages = self.max_history * 2
        if len(self.sessions[session_id]) > max_messages:
            self.sessions[session_id] = self.sessions[session_id][-max_messages :]

    def get_history(self, session_id: str) -> List[Messages]:
        """获取历史会话"""
        if session_id not in self.sessions and self.storage:
            row = self.storage.get_messages(session_id, self.max_history *2)
            self.sessions[session_id] = [Messages(**row) for row in row]
        return self.sessions.get(session_id, [])
    
    def build_context(self, session_id: str, current_input: str) -> str:
        """ 
        将历史对话和当前输入拼成完整上下文，传给 TaskRouter。
        如果没有历史，直接返回当前输入。
        """
        history = self.get_history(session_id)
        if not history:
            return current_input
        
        context = "以下是之前的对话记录，请根据上下文理解用户的当前需求：\n"
        for msg in history:
            if msg.role == "user":
                context += f"用户: {msg.content}\n"
            else:
                try:
                    data = json.loads(msg.content)
                    if isinstance(data, dict) and "results" in data:
                        parts = []
                        for r in data["results"]:
                            rtype = r.get("type", "")
                            if rtype == "image" and r.get("url"):
                                parts.append(f"上一步生成了一张图片，URL是：{r['url']}")
                            elif rtype == "text" and r.get("content"):
                                parts.append(f"上一步生成了文本：{r['content']}")
                        if parts:
                            context += f"助手: {'；'.join(parts)}\n"
                        else:
                            context += f"助手: {msg.content}\n"
                    else:
                        context += f"助手: {msg.content}\n"
                except (json.JSONDecodeError, TypeError):
                    context += f"助手: {msg.content}\n"

        return context

    def add_assistant_response(self, session_id: str, results: list) -> None:
        """将子任务执行结果摘要以助手角色存入对话记忆"""
        if not results:
            return
        summary = " | ".join([r.content or r.url for r in results if r.content or r.url])
        self.add(session_id, "assistant", summary)

    def has_session(self, session_id: str) -> bool:
        """前端检查会话是否已在记忆缓存中"""
        return session_id in self.sessions

    def delete_session(self, session_id: str) -> None:
        """删除指定会话的全部记忆"""
        self.sessions.pop(session_id, None)