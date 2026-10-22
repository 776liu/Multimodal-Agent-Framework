from typing import List, Dict, Optional
from src.core.models import Messages
import json


class Memory:
    """会话记忆，存储和检索历史对话"""
    # 多 Agent 私有作用域统一使用该键（升级计划 4.4）
    PUBLIC_SCOPE = "__public__"

    def __init__(self, max_history: int = 10, storage = None):
        self.max_history = max_history
        self.storage = storage
        self.sessions: Dict[str, List[Messages]] = {}
        # Agent 维度私有记忆: agent_id -> scope_key -> List[Messages]
        # 仅进程内缓存，不落 SQLite（对话正文仍由 Worker 统一持久化）
        self.agent_sessions: Dict[str, Dict[str, List[Messages]]] = {}


    def add(self, session_id: str, role: str, content: str) ->None:
        """添加一条消息到进程内缓存。

        注意：这里不再写 Storage——持久化由 Worker 统一直写（单一写入者原则），
        避免 Agent 与 Worker 双路径各写一次导致消息重复。
        """
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
        """将历史对话与当前指令拼成结构化上下文，供 TaskRouter 拆解。

        输出结构（有历史时）：
            <history>
            用户: ...
            助手: ...
            </history>
            <current_request>当前指令</current_request>

        无历史时直接返回 current_input（不加标记，保持单轮语义简洁）。

        注意调用约定：调用方通常**先** `add(session_id, "user", current_input)`
        **再**调用本方法，因此历史末尾那条 user 消息就是当前输入本身。
        这里会把它从 <history> 中剔除，只在 <current_request> 中出现一次，
        避免同一指令出现两遍而被模型当成两个待办任务（多轮重复执行的根因之一）。
        """
        history = self.get_history(session_id)
        if not history:
            return current_input

        # 剔除末尾的当前输入（调用方已提前 add 进历史），避免重复出现
        tail = history[-1]
        if tail.role == "user" and tail.content.strip() == current_input.strip():
            history = history[:-1]

        if not history:
            return current_input

        context = "<history>\n"
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
                            elif rtype == "video" and r.get("url"):
                                parts.append(f"上一步生成了一段视频，URL是：{r['url']}")
                        if parts:
                            context += f"助手: {'；'.join(parts)}\n"
                        else:
                            context += f"助手: {msg.content}\n"
                    else:
                        context += f"助手: {msg.content}\n"
                except (json.JSONDecodeError, TypeError):
                    context += f"助手: {msg.content}\n"
        context += "</history>\n"
        context += f"<current_request>{current_input}</current_request>"

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

    # ==================================================================
    # Agent 维度隔离（升级计划 4.4）
    # 设计: 对话正文仍走 PUBLIC_SCOPE（供前端与 TaskRouter 使用），
    #       各 Agent 的中间推理/工具记录走自己的 agent_id 作用域，
    #       避免 Image Agent 被长文本对话历史污染画面提示词。
    # ==================================================================
    def add_agent_message(self, session_id: str, agent_id: str,
                          role: str, content: str, scope: str = "private") -> None:
        """写入某 Agent 的记忆

        scope="private": 仅该 Agent 可见（默认）
        scope="public" : 写入公共对话流（等价于 add）
        """
        if scope == "public":
            self.add(session_id, role, content)
            return

        key = f"{agent_id}::{session_id}"
        self.agent_sessions.setdefault(agent_id, {}).setdefault(key, [])
        self.agent_sessions[agent_id][key].append(Messages(role=role, content=content))

        max_messages = self.max_history * 2
        if len(self.agent_sessions[agent_id][key]) > max_messages:
            self.agent_sessions[agent_id][key] = \
                self.agent_sessions[agent_id][key][-max_messages:]

    def get_agent_history(self, session_id: str, agent_id: str,
                          include_public: bool = False) -> List[Messages]:
        """取某 Agent 的私有记忆；include_public=True 时前置公共历史"""
        key = f"{agent_id}::{session_id}"
        private = list(self.agent_sessions.get(agent_id, {}).get(key, []))
        if not include_public:
            return private
        return list(self.get_history(session_id)) + private

    def clear_agent_memory(self, session_id: str, agent_id: Optional[str] = None) -> None:
        """清理记忆。agent_id 为 None 时清理该会话全部 Agent 私有记忆"""
        if agent_id is None:
            for aid in list(self.agent_sessions.keys()):
                self.agent_sessions[aid].pop(f"{aid}::{session_id}", None)
            return
        self.agent_sessions.get(agent_id, {}).pop(f"{agent_id}::{session_id}", None)

    def delete_session(self, session_id: str) -> None:
        """删除会话全部记忆（含各 Agent 私有作用域）"""
        self.sessions.pop(session_id, None)
        self.clear_agent_memory(session_id, None)
