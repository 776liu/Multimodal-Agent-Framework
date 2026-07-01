from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
from src.api import create_agent
from src.api.redis_task_manager import RedisTaskManager
from src.api.worker import Worker
import threading

class TaskRequest(BaseModel):
    user_input: str
    session_id: str = "default"


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


@app.post("/api/task/submit", status_code=202)
async def submit_task(task: TaskRequest, request: Request):
    """提交任务:接收用户输入和会话ID,创建任务并返回 task_id"""
    task_manager = request.app.state.task_manager
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
    """"""
    storage = request.app.state.storage
    sessions = storage.list_sessions()
    return {"sessions": sessions}