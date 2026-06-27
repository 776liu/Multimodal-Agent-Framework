from typing import List,Dict
from src.core.models import Messages


class Memory:
    """会话记忆，存储和检索历史对话"""
    def __init__(self, max_history: int = 10):
        self.max_history = max_history
        self.sessions: Dict[str, List[Messages]] = {}

    def add(self, session_id: str, role: str, content: str) ->None:
        """添加一条消息到会话"""

        if session_id not in self.sessions:
            self.sessions[session_id] = []
        self.sessions[session_id].append(Messages(role=role, content=content))

        max_messages = self.max_history * 2
        if len(self.sessions[session_id]) > max_messages:
            self.sessions[session_id] = self.sessions[session_id][-max_messages :]

    def get_history(self, session_id: str) -> List[Messages]:
        """获取历史会话"""
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
            role_name = "用户" if msg.role == "user" else "助手"
            context +=f"[{role_name}]: {msg.content}\n"
        context += f"\n用户的当前需求: {current_input}"

        return context

    def add_assistant_response(self, session_id: str, results: list) -> None:
        """将子任务执行结果摘要以助手角色存入对话记忆"""
        if not results:
            return
        summary = " | ".join([r.content or r.url for r in results if r.content or r.url])
        self.add(session_id, "assistant", summary)