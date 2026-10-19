"""多 Agent 协作数据契约（升级计划 阶段一）

本模块定义 Orchestrator 与各专业 Agent 之间的标准通信格式：
- Artifact   : 单个产物（文本/图片/视频/文件），Agent 间传递数据的最小单元
- AgentMessage: Orchestrator 派发给 Agent 的指令消息
- AgentResponse: Agent 返回给 Orchestrator 的执行结果
- TaskContext : 一次任务贯穿始终的上下文（会话、计划、重试计数）

设计原则：
1. 与现有 models.py（单 Agent 时代的数据类）并存，不破坏存量代码；
2. 全部为 dataclass，支持 to_dict/from_dict 以便落库与跨进程传递；
3. 契约先于实现：本阶段只定义结构，不接入主流程（阶段三才由 Orchestrator 调度）。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---- 产物品类常量 ----
ARTIFACT_TEXT = "text"
ARTIFACT_IMAGE = "image"
ARTIFACT_VIDEO = "video"
ARTIFACT_FILE = "file"

# ---- 响应状态常量 ----
STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"
STATUS_NEED_REVISION = "NEED_REVISION"   # Reviewer 审查不通过，请求重做


@dataclass
class Artifact:
    """Agent 间传递的产物单元

    text   -> content 为文本正文
    image  -> content 为图片 URL
    video  -> content 为视频 URL
    file   -> content 为文件路径或 URL

    metadata 用于携带附加信息，如：
        {"step": 1, "model": "Tongyi-MAI/Z-Image-Turbo", "prompt": "...", "size_kb": 1536}
    """
    type: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def text_of(cls, content: str, **metadata) -> "Artifact":
        return cls(type=ARTIFACT_TEXT, content=content, metadata=dict(metadata))

    @classmethod
    def image_of(cls, url: str, **metadata) -> "Artifact":
        return cls(type=ARTIFACT_IMAGE, content=url, metadata=dict(metadata))

    @classmethod
    def video_of(cls, url: str, **metadata) -> "Artifact":
        return cls(type=ARTIFACT_VIDEO, content=url, metadata=dict(metadata))

    def to_dict(self) -> dict:
        return {"type": self.type, "content": self.content, "metadata": self.metadata}

    @classmethod
    def from_dict(cls, data: dict) -> "Artifact":
        return cls(
            type=data.get("type", ARTIFACT_TEXT),
            content=data.get("content", ""),
            metadata=data.get("metadata") or {},
        )

    def to_task_result(self):
        """转换为存量 TaskResult，便于复用现有 Builder/Storage 链路"""
        from src.core.models import TaskResult
        if self.type in (ARTIFACT_IMAGE, ARTIFACT_VIDEO, ARTIFACT_FILE):
            return TaskResult(type=self.type, url=self.content)
        return TaskResult(type=ARTIFACT_TEXT, content=self.content)


@dataclass
class AgentMessage:
    """Orchestrator → Agent 的派发指令

    artifacts 携带上游步骤的产物，下游 Agent 据此做多模态输入
    （例如 Image Agent 产出的图片，注入 Writer Agent 的视觉输入）。
    """
    task_id: str
    step: int
    sender: str                 # 发起方，恒为 Orchestrator
    receiver: str               # 目标 Agent 名
    prompt: str                 # 子任务提示词
    capability: str = ""        # 该步骤要求的能力标签
    session_id: str = "default" # 归属会话，用于 agent_messages 落库
    artifacts: List[Artifact] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "step": self.step,
            "sender": self.sender,
            "receiver": self.receiver,
            "prompt": self.prompt,
            "capability": self.capability,
            "session_id": self.session_id,
            "artifacts": [a.to_dict() for a in self.artifacts],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentMessage":
        return cls(
            task_id=data["task_id"],
            step=data.get("step", 0),
            sender=data.get("sender", "orchestrator"),
            receiver=data.get("receiver", ""),
            prompt=data.get("prompt", ""),
            capability=data.get("capability", ""),
            session_id=data.get("session_id", "default"),
            artifacts=[Artifact.from_dict(a) for a in data.get("artifacts") or []],
        )

    def artifacts_of_type(self, artifact_type: str) -> List[Artifact]:
        """提取指定类型的产物，便于下游取用（如 Writer 只取 image 走视觉输入）"""
        return [a for a in self.artifacts if a.type == artifact_type]

    @property
    def first_image_url(self) -> str:
        imgs = self.artifacts_of_type(ARTIFACT_IMAGE)
        return imgs[0].content if imgs else ""


@dataclass
class AgentResponse:
    """Agent → Orchestrator 的执行结果

    status = NEED_REVISION 时，issues 携带 Reviewer 的修改建议，
    Orchestrator 据此触发反思重试（受 max_retries 约束，防死循环）。
    """
    status: str
    agent_name: str = ""
    output_text: str = ""
    artifacts: List[Artifact] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    error_code: Optional[int] = None

    @property
    def ok(self) -> bool:
        return self.status == STATUS_SUCCESS

    @classmethod
    def success(cls, agent_name: str, artifacts: List[Artifact] = None, output_text: str = "") -> "AgentResponse":
        return cls(status=STATUS_SUCCESS, agent_name=agent_name,
                   artifacts=artifacts or [], output_text=output_text)

    @classmethod
    def failed(cls, agent_name: str, error_code: int = -1, issues: List[str] = None) -> "AgentResponse":
        return cls(status=STATUS_FAILED, agent_name=agent_name,
                   error_code=error_code, issues=issues or [])

    @classmethod
    def need_revision(cls, agent_name: str, issues: List[str]) -> "AgentResponse":
        return cls(status=STATUS_NEED_REVISION, agent_name=agent_name, issues=issues)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "agent_name": self.agent_name,
            "output_text": self.output_text,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "issues": list(self.issues),
            "error_code": self.error_code,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentResponse":
        return cls(
            status=data.get("status", STATUS_FAILED),
            agent_name=data.get("agent_name", ""),
            output_text=data.get("output_text", ""),
            artifacts=[Artifact.from_dict(a) for a in data.get("artifacts") or []],
            issues=list(data.get("issues") or []),
            error_code=data.get("error_code"),
        )


@dataclass
class TaskContext:
    """一次任务贯穿始终的上下文

    Orchestrator 持有并透传给各 Agent：
    - session_id : 归属会话
    - user_input : 原始用户输入
    - max_retries: 反思重试上限（升级计划 4.6，防死循环）
    - step_outputs: step -> Artifact 列表，替代旧 Agent 里的 step_outputs 单字典，
      用于把上游产物（含文本）传递给下游步骤。
    """
    task_id: str
    session_id: str = "default"
    user_input: str = ""
    max_retries: int = 2
    step_outputs: Dict[int, List[Artifact]] = field(default_factory=dict)
    attempt: Dict[int, int] = field(default_factory=dict)   # step -> 已重试次数

    def record(self, step: int, artifacts: List[Artifact]) -> None:
        """记录某步骤产物，供下游取用"""
        self.step_outputs.setdefault(step, []).extend(artifacts)

    def upstream_of(self, step: int) -> List[Artifact]:
        """取某步骤之前所有上游产物（按 step 顺序）"""
        out: List[Artifact] = []
        for s in sorted(self.step_outputs.keys()):
            if s < step:
                out.extend(self.step_outputs[s])
        return out

    def can_retry(self, step: int) -> bool:
        return self.attempt.get(step, 0) < self.max_retries

    def bump(self, step: int) -> int:
        self.attempt[step] = self.attempt.get(step, 0) + 1
        return self.attempt[step]
