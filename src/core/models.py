from dataclasses import dataclass, field
from typing import List,Dict, Optional, Any

@dataclass
class ModelInfo:
    """模型注册信息，对应 Router 的输出"""
    model_name: str
    endpoint: str
    api_key: str
    capability: str        

@dataclass
class Subtask:
    """单个子任务，对应 TaskRouter 输出里的 subtasks 数组元素"""
    step: int
    capability: str
    prompt: str

@dataclass
class ExecutionPlan:
    """执行计划，对应 TaskRouter 输出"""
    intent: str
    task_id: str
    subtasks: List[Subtask] = field(default_factory=list)

@dataclass
class TaskResult:
    """子任务的执行结果"""
    type: str
    url: Optional[str] = None
    content: Optional[str] = None

@dataclass
class LLMResponse:
    """大模型的输出"""
    status: str
    data: Optional[TaskResult] = None
    error_code: Optional[int] = None
    model_name: str = ""

@dataclass
class CallChainEntry:
    """调用链日志的单条记录"""
    model_name: str
    capability: str
    status: str
    error_code: Optional[int] = None
    attempted_at: str = ""

@dataclass
class BuilderInput:
    """构建器输入"""
    task_id: str
    final_status: str
    results: List[TaskResult] = field(default_factory=list)
    call_chain: List[CallChainEntry] = field(default_factory=list)

@dataclass
class BuilderOutput:
    frontend_response: Dict[str, Any]
    log_record: Dict[str, Any]