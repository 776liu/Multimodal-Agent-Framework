# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 文档语言规定

**所有文档（包括 CLAUDE.md、需求文档、模块说明、注释中的长段说明、README、commit message）均使用中文书写。** 代码标识符（变量名、函数名、类名、模块名）使用英文。

## 项目概述

多模态 Agent 框架（Multimodal Agent Framework）—— 一个 Python AI Agent 编排系统。接收用户的自然语言输入，将其拆解为子任务（文本生成、图片生成），为每个子任务匹配最合适的大模型并自动执行降级切换，最终拼装统一的 JSON 响应返回给前端。底层对接阿里云百炼模型。

## 常用命令

```bash
# 安装（可编辑模式）
pip install -e .

# 运行 Streamlit UI（前端界面）
.venv/Scripts/streamlit run src/ui/app.py

# 运行 FastAPI 服务端（异步任务模式）
.venv/Scripts/uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload

# 运行全部测试
.venv/Scripts/pytest tests/ -v

# 运行单个测试文件
.venv/Scripts/pytest tests/test_agent.py -v

# 运行含指定关键字的测试
.venv/Scripts/pytest tests/ -v -k "fallback"

# 运行特定参数化用例
.venv/Scripts/pytest tests/test_agent.py::test_agent_scenarios\[把Hello World翻译成中文-single_text\] -v
```

## 架构

系统包含 8 个模块，提供两种运行模式：**Streamlit UI**（同步交互）和 **FastAPI**（异步任务提交+轮询）。

### 核心管线（两种模式共用）

```
[用户输入] → Agent（状态机总控）
               ├─ Memory（多轮对话上下文拼接）
               ├─ TaskRouter（LLM 驱动意图解析 → 生成 ExecutionPlan）
               ├─ Router（模型注册中心，从 model.yaml 读取配置）
               ├─ llmClient（无状态 HTTP 调用，对接模型端点）
               ├─ Builder（拼装 frontend_response + log_record）
               └─ Storage（SQLite 持久化会话消息 + 任务日志）
```

### API 模式（异步任务）

FastAPI 启动时通过 `create_agent()`（[src/api/__init__.py](src/api/__init__.py)）装配核心引擎，将 Agent 实例注入 Worker 后台线程：

```
[POST /api/task/submit] → MemoryTaskManager.create_task → 返回 task_id + "pending"
[Worker 后台线程]       → 轮询 MemoryTaskManager.dequeue() → agent.run() → 更新状态 + 写入 Storage
[GET /api/task/{id}]    → MemoryTaskManager.get_task() → 返回当前状态/结果
```

### 各模块职责

- **Agent**（[src/core/agent.py](src/core/agent.py)）：总控制器，驱动状态机流转。`run()` 方法接受可选的 `on_progress` 回调，用于 Streamlit 实时进度展示。
- **TaskRouter**（[src/core/task_router.py](src/core/task_router.py)）：用 LLM 解析用户意图，输出 `ExecutionPlan`（含有序 `Subtask` 列表）。内部有一个固定的 `SYSTEM_PROMPT` 定义三种意图类型（`single_text`、`single_multimodal`、`multi_step_multimodal`）和输出 JSON schema。
- **Router**（[src/core/router.py](src/core/router.py)）：模型注册中心。从 `config/model.yaml` 加载模型列表，根据 `capability` 返回优先级最高的可用模型，重试时排除已失败模型。
- **llmClient**（[src/core/llm_client.py](src/core/llm_client.py)）：无状态 HTTP 调用器。文本生成用兼容模式端点（请求体 `{model, messages}`），图片生成用原生 API（请求体 `{model, input, parameters}`）。默认超时：文本 60s，图片 300s。**不负责重试或降级逻辑。**
- **Builder**（[src/core/builder.py](src/core/builder.py)）：生成两份输出——`frontend_response`（面向用户，失败时隐藏内部错误码）和 `log_record`（含完整调用链和 error_summary）。同时将日志写入 `logs/{task_id}.json` 和 SQLite。
- **Memory**（[src/core/memory.py](src/core/memory.py)）：会话记忆模块。缓存最近 N 轮对话（`max_history` 控制轮数，默认 10），`build_context()` 将历史拼接为 "之前的对话记录" 上下文注入 TaskRouter。超出 `max_history * 2` 条时自动滚动淘汰。
- **Storage**（[src/core/storage.py](src/core/storage.py)）：SQLite 持久化（WAL 模式）。三张表：`sessions`（会话元数据+标签）、`messages`（对话消息）、`task_logs`（任务日志含 results_json/call_chain_json）。支持 `list_sessions()`（按时间降序）、`delete_session_data()`（级联删除）。
- **Worker**（[src/api/worker.py](src/api/worker.py)）：后台线程消费者，轮询 MemoryTaskManager 队列取 pending 任务 → 调用 Agent → 写回结果并持久化。

### 数据模型

详见 [src/core/models.py](src/core/models.py)：
- `ModelInfo`：模型注册信息（registered_name, model_name, endpoint, api_key, capability）
- `Subtask`：子任务（step, capability, prompt, image_url, reference_step）
- `ExecutionPlan`：执行计划（intent, task_id, subtasks）
- `TaskResult`：子任务结果（type: text|image, url?, content?）
- `LLMResponse`：LLM 调用响应（status, data: TaskResult, error_code, model_name）
- `CallChainEntry`：调用链日志（model_name, capability, status, error_code, attempted_at）
- `BuilderInput` / `BuilderOutput`：构建器输入/输出
- `Messages` / `Conversatoin`：对话消息与多轮会话

### 状态机流转

- `READY` → 接收用户输入，生成 `task_id`，从 Memory 拼接上下文 → `PLANNING`
- `PLANNING` → TaskRouter.route_task()；成功 → `ROUTING`，失败 → `FAILED`
- `ROUTING` → Router.get_model(capability, failed_models)；成功 → `CALLING`，`NO_AVAILABLE_MODEL` → 检查已有成功子任务：有 → `PARTIAL_SUCCESS`，无 → `FAILED`
- `CALLING` → llmClient.call()；成功 → 记录到 call_chain + 检查剩余子任务（有 → `ROUTING`，无 → `SUCCESS`）；失败 → 将 model 加入 failed_models 回到 `ROUTING`
- 终态：`SUCCESS`（所有子任务成功）、`PARTIAL_SUCCESS`（至少一个成功 + 至少一个耗尽）、`FAILED`（全部耗尽）

### 已注册模型

配置在 `config/model.yaml`（真实密钥，勿提交）和 `config/models.example.yaml`（模板，无密钥）。

| 注册名 | 能力标签 | 百炼模型 | 端点类型 |
|--------|---------|---------|---------|
| qwen-plus | text-generation | qwen3.7-plus | 兼容模式 |
| qwen-max | text-generation | qwen3.7-max-2026-06-08 | 兼容模式 |
| qwen3.5-plus | text-generation | qwen3.5-plus-2026-04-20 | 兼容模式 |
| qwen-image | image-generation | qwen-image-2.0-pro-2026-04-22 | 原生 API |
| wan-image | image-generation | wan2.7-image-pro | 原生 API |
| task-router-model | text-generation | qwen3.7-plus | 兼容模式（仅用于 TaskRouter） |

### 错误码表

| 错误码 | 含义 | 发生位置 | 处理策略 |
|--------|------|---------|---------|
| 503 | 服务不可用 / 连接失败 | llmClient | 切换备选模型 |
| 401 | Key 错误 | llmClient | 切换备选模型 |
| 408 | 调用超时 | llmClient | 切换备选模型 |
| INTENT_PARSE_FAILED | 意图识别失败 | TaskRouter | 返回失败，提示更换提示词 |
| NO_AVAILABLE_MODEL | 无可用模型 | Router | 任务失败 |
| ALL_MODELS_EXHAUSTED | 所有模型耗尽 | Agent | 任务失败 |

## 目录结构

```
src/
  core/       # Agent、TaskRouter、Router、llmClient、Builder、Memory、Storage、models
  adapters/   # config.py（YAML 配置加载）
  api/        # FastAPI 服务端（main.py, task_manager.py, worker.py, __init__.py）
  ui/         # Streamlit 前端界面（app.py）
config/       # model.yaml（真实配置）、models.example.yaml（模板）、model.test.yaml（测试用）
tests/        # pytest 测试
docs/         # 需求文档和模块规格说明
data/         # SQLite 数据库文件（agent.db），自动创建
logs/         # 任务日志 JSON，由 Builder 自动写入
```

## 配置规范

- 模型配置：`config/model.yaml`（YAML），通过 [src/adapters/config.py](src/adapters/config.py) 中的 `load_model_config()` 加载
- `config/models.example.yaml` 为模板文件，不含真实密钥，可安全提交
- `config/model.test.yaml` 用于容错链路测试（含一个不可达的首选 + 可达的备选）
- **严禁**在代码中硬编码 `endpoint` 和 `api_key`

## 两种运行模式

### Streamlit UI（同步）

`src/ui/app.py`：完整的 Web 交互界面，支持多会话管理（侧边栏新建/切换/删除会话）、实时进度展示（调用链时间线）、历史记录查看。Agent 通过 `on_progress` 回调驱动进度条和状态文本更新。Memory 和 Storage 持久化多轮对话。

### FastAPI（异步任务）

`src/api/main.py`：两个端点——`POST /api/task/submit` 提交任务返回 202，`GET /api/task/{task_id}` 查询状态。Worker 后台线程消费队列。当前使用 `MemoryTaskManager`（内存字典 + 线程锁），不依赖 Redis。

## 测试

- `tests/test_agent.py`：端到端场景测试（参数化：翻译/图片/图片+描述），含容错链路测试（`test_agent_fallback_success`）验证模型降级逻辑
- `tests/test_llm_client.py`：单模型调用测试（文本/图片），非 pytest 断言式（手动验证输出）
- `tests/test_api.py`：FastAPI 异步任务提交+轮询测试，需先启动 uvicorn 服务端
- `tests/test_task_router.py`：TaskRouter 单模块测试，非 pytest 断言式

测试依赖真实 API 端点和有效密钥（`config/model.yaml`）。

## 命名约定

- 模块名、类名、函数名、变量名使用英文
- 需求和文档使用中文
- 数据模型字段使用 snake_case

## 响应格式

无论成功/失败/部分成功，每次 `agent.run()` 返回均包含两部分：
- `frontend_response`：面向用户，失败时屏蔽内部错误细节，仅返回可读提示
- `log_record`：含完整调用链（时间戳、错误码、`error_summary`），供开发调试
