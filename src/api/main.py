from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
from src.api import create_agent
from src.api.task_manager import MemoryTaskManager
from src.api.worker import Worker
import threading
from src.api.redis_task_manager import RedisTaskManager

class TaskRequest(BaseModel):
    user_input: str
    session_id: str = "default"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：装配引擎 → 创建队列 → 启动 Worker,关闭时通知退出"""
    agent, storage = create_agent()

    task_manager = RedisTaskManager()
    app.state.task_manager = task_manager

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
