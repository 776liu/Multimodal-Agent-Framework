
# 多模态 AI Agent 框架

一个能接收用户复杂需求、自动拆解任务、调度最优大模型、执行并验证结果的 Agent 编排框架。底层对接阿里云百炼模型，提供 Streamlit 前端和 FastAPI 异步任务两种运行模式。

---

## 架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Streamlit 前端                             │
│                       (src/ui/app.py)                               │
│                  会话管理 · 实时进度 · 历史记录                        │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ HTTP (轮询)
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        FastAPI 服务端                                │
│                      (src/api/main.py)                              │
│                                                                     │
│   POST /api/task/submit ──→ Redis 队列 ──→ Worker 后台线程           │
│   GET  /api/task/{id}     ◄── 查询状态 ◄───┘                        │
│   GET  /api/sessions                                                │
│   GET  /api/session/{id}/history                                    │
│   GET  /api/session/{id}/tasks                                      │
│   DELETE /api/session/{id}/history                                  │
└───────────────┬─────────────────┬───────────────────────────────────┘
                │                 │
       ┌────────▼────────┐   ┌───▼───────────┐
       │   Redis 队列     │   │    SQLite      │
       │  (任务队列/状态)  │   │  (会话/消息/日志)│
       └─────────────────┘   └───────────────┘
                │
       ┌────────▼────────────────────────────────────────────────────┐
       │                    核心引擎 (src/core/)                       │
       │                                                             │
       │  ┌──────────┐   ┌────────────┐   ┌──────────────────┐       │
       │  │  Agent   │──→│ TaskRouter │──→│     Router       │       │
       │  │ (状态机)  │   │ (意图解析)  │   │  (模型注册/匹配)   │       │
       │  └──────────┘   └────────────┘   └────────┬─────────┘       │
       │                                           │                  │
       │                    ┌──────────────────────┘                  │
       │                    ▼                                         │
       │  ┌──────────┐   ┌──────────┐   ┌──────────────┐             │
       │  │  Memory  │   │LLMClient │   │   Builder    │             │
       │  │(多轮对话) │   │(HTTP调用) │   │ (拼装响应/日志)│             │
       │  └──────────┘   └──────────┘   └──────────────┘             │
       └─────────────────────────────────────────────────────────────┘
```

---

## 快速开始

### 环境要求

- Python 3.10+
- Redis（任务队列）

### 1. 安装依赖

```bash
git clone <your-repo-url>
cd "Multimodal Agent Framework"
pip install -r requirements.txt
```

### 2. 配置模型

```bash
cp config/models.example.yaml config/models.yaml
```

编辑 `config/model.yaml`，填入模型的真实 `api_key` 和 `model_name`：

```yaml
models:
  - model_name: "model-x"
    api_key: "sk-xxxxxxxxxxxxxxxx"
    capability: "text-generation"
    ...
```

`config/models.example.yaml` 为模板文件，可安全提交到版本控制。

### 3. 启动 Redis

```bash
redis-server
```

### 4. 启动后端

```bash
uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload
```

### 5. 启动前端

```bash
streamlit run src/ui/app.py
```

浏览器访问 Streamlit 提供的地址（默认 `http://localhost:8501`），即可在 Web 界面中输入自然语言指令。

---

## API 端点

| 方法 | 路径 | 职责 |
|------|------|------|
| `POST` | `/api/task/submit` | 提交任务：接收用户输入和会话 ID，返回 `task_id` |
| `GET` | `/api/task/{task_id}` | 查询任务状态：返回任务当前状态与执行结果 |
| `GET` | `/api/sessions` | 获取全部会话列表 |
| `GET` | `/api/session/{session_id}/history` | 获取指定会话的对话消息与历史任务 |
| `GET` | `/api/session/{session_id}/tasks` | 获取指定会话的进行中与已完成任务 |
| `DELETE` | `/api/session/{session_id}/history` | 删除指定会话的所有消息和历史任务 |

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| Web 框架 | FastAPI |
| 任务队列 | Redis |
| 持久化 | SQLite（WAL 模式） |
| 前端 | Streamlit |
| 模型服务 | 阿里云百炼 API |
| 测试 | pytest |

---

## 项目结构

```
src/
  core/                  # 核心引擎
    agent.py             # 总控状态机，驱动任务执行流程
    task_router.py       # LLM 意图解析，生成执行计划（ExecutionPlan）
    router.py            # 模型注册中心，按能力匹配最优模型
    llm_client.py        # 无状态 HTTP 调用器，对接模型端点
    builder.py           # 拼装面向用户的响应与调试日志
    memory.py            # 多轮对话上下文管理
    storage.py           # SQLite 持久化（会话、消息、任务日志）
    models.py            # 数据模型定义（dataclass）
  api/                   # FastAPI 服务端
    main.py              # API 路由与应用入口
    redis_task_manager.py# Redis 任务队列（入队/出队/状态查询）
    worker.py            # 后台消费者线程
    task_manager.py      # 任务管理器接口
  ui/
    app.py               # Streamlit 交互界面
  adapters/
    config.py            # YAML 配置加载
config/
  models.example.yaml    # 模型配置模板
  model.yaml             # 实际模型配置（不提交）
tests/                   # pytest 测试用例
```

---

## 设计亮点

- **状态机驱动的任务编排**：Agent 内部以有限状态机（`READY → PLANNING → ROUTING → CALLING → SUCCESS / FAILED`）组织流程，每个状态职责单一、转移条件明确，复杂调度逻辑可预测且易于调试。

- **模型降级与容错**：Router 按优先级注册同类能力的多个模型。当首选模型因网络、限流或密钥问题不可用时，自动切换至备选模型；全部模型耗尽前不放弃任务，最大化任务成功率。

- **意图解析与执行计划分离**：TaskRouter 负责将自然语言拆解为结构化的 `ExecutionPlan`（含有序子任务和能力标签），Agent 仅按计划执行。意图策略变更不影响执行编排，执行层优化也不干扰意图判断。

- **多轮对话上下文注入**：Memory 模块自动缓存最近 N 轮对话，每次任务执行前将历史拼接为上下文注入 TaskRouter，使模型能理解省略、指代和追加指令，实现自然的连续对话体验。

- **面向用户与面向开发的双输出**：Builder 同时生成 `frontend_response`（面向终端用户，失败时隐藏内部错误码）和 `log_record`（含完整调用链、时间戳和错误摘要），兼顾用户体验与问题排查效率。
