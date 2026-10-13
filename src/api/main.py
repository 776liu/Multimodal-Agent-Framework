from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager
from src.api import create_agent
from src.api.redis_task_manager import RedisTaskManager
from src.api.worker import Worker
import threading

class TaskRequest(BaseModel):
    user_input: str
    session_id: str = "default"


class SessionCreateRequest(BaseModel):
    label: str = "新对话"


class SessionRenameRequest(BaseModel):
    label: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：装配引擎 → 创建队列 → 启动 Worker,关闭时通知退出"""
    agent, storage = create_agent()

    task_manager = RedisTaskManager()
    app.state.task_manager = task_manager
    app.state.storage = storage

    stop_event = threading.Event()
    worker = Worker(agent, task_manager, storage, stop_event)
    worker_thread = threading.Thread(target=worker.run, name="api-worker", daemon=True)
    worker_thread.start()

    yield

    stop_event.set()
    worker_thread.join(timeout=5)


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/task/submit", status_code=202)
async def submit_task(task: TaskRequest, request: Request):
    """提交任务:接收用户输入和会话ID,创建任务并返回 task_id"""
    task_manager = request.app.state.task_manager
    storage = request.app.state.storage

    # 会话兜底登记：任何一次提交都保证 session 已登记到 sessions 表
    storage.ensure_session(task.session_id)

    result = task_manager.create_task(task.user_input, task.session_id)
    return result


@app.get("/api/task/{task_id}")
async def get_task(task_id: str, request: Request):
    """查询任务状态：根据 task_id 返回任务当前状态和结果"""
    task_manager = request.app.state.task_manager

    status = task_manager.get_task(task_id)
    if status is not None:
        return status
    else:
        raise HTTPException(status_code=404, detail="Task not found")

@app.get("/api/session/{session_id}/history")
async def get_conversation_history(session_id: str, request: Request):
    """获取会话的对话历史和任务历史"""
    storage = request.app.state.storage
    messages = storage.get_messages(session_id, limit=50)
    tasks = storage.get_task_history(session_id, limit=50)
    return {
        "session_id": session_id,
        "messages": messages,
        "tasks": tasks
    }

@app.get("/api/session/{session_id}/tasks")
async def get_session_tasks(session_id: str, request: Request):
    """任务查询"""
    task_manager = request.app.state.task_manager
    storage = request.app.state.storage

    processing_tasks = task_manager.get_task_by_session(session_id)
    compiled_tasks = storage.get_task_history(session_id, limit = 20)

    return {
        "session_id": session_id,
        "processing": processing_tasks,
        "completed": compiled_tasks
    }

@app.get("/api/sessions")
async def list_sessions(request: Request):
    """列出全部会话（sessions 表主分支, 兜底分支兼容历史数据）"""
    storage = request.app.state.storage
    sessions = storage.list_sessions()
    return {"sessions": sessions}


@app.post("/api/sessions", status_code=201)
async def create_session(body: SessionCreateRequest, request: Request):
    """显式创建会话（前端"新建会话"按钮调用），返回会话元数据"""
    storage = request.app.state.storage
    import uuid
    session_id = f"session_{uuid.uuid4().hex[:12]}"
    storage.save_session(session_id, body.label)
    sessions = {s["session_id"]: s for s in storage.list_sessions()}
    return sessions.get(session_id, {
        "session_id": session_id,
        "label": body.label,
        "created_at": None,
    })


@app.patch("/api/session/{session_id}")
async def rename_session(session_id: str, body: SessionRenameRequest, request: Request):
    """重命名会话标签"""
    storage = request.app.state.storage
    if not storage.rename_session(session_id, body.label):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "label": body.label}


@app.delete("/api/session/{session_id}", status_code=204)
async def delete_session(session_id: str, request: Request) -> None:
    """删除整个会话：元数据 + 消息 + 任务日志 + 审计记录 + Redis 在途任务"""
    storage = request.app.state.storage
    task_manager = request.app.state.task_manager

    # 在途任务标记失败，防止 Worker 之后写回已删除会话的数据
    for task in task_manager.get_task_by_session(session_id):
        task_manager.update_task(task["task_id"], "FAILED", {"error": "Session deleted"})

    storage.delete_session_audits(session_id)
    storage.delete_session_data(session_id)


@app.delete("/api/session/{session_id}/history", status_code=204)
async def delete_conversation_history(session_id: str, request: Request)-> None:
    """删除会话的对话历史和任务历史（保留会话本身）"""
    storage = request.app.state.storage
    task_manager = request.app.state.task_manager
    for task in task_manager.get_task_by_session(session_id):
        task_manager.update_task(task["task_id"], "FAILED", {"error: Conversation history deleted"})

    storage.delete_messages(session_id)
    storage.delete_task_history(session_id)