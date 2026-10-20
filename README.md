# 多模态 AI Agent 协作框架

一个基于 **多 Agent 协作** 的多模态内容生成系统：接收用户一句自然语言指令，
自动拆解任务、按能力调度专业 Agent 与最优大模型、执行、审查，最终产出
**文本 + 图片 + 视频** 的组合结果。

> 演进说明：项目早期为「单 Agent 调度多模型」架构（Streamlit 前端 + 阿里云百炼），
> 现已演进为「多 Agent 协作」架构（React 前端 + 可插拔模型平台）。
> 旧单 Agent 仍保留（`create_agent(multi_agent=False)`），用作架构对比实验的基线。

---

## 核心特性

- **多 Agent 协作编排**：Orchestrator 负责拆解与调度，WriterAgent（文本）/ ImageAgent（图像）/
  VideoAgent（视频）/ ReviewerAgent（质检）各司其职，协作轨迹全量落库可回放。
- **一句话生成多模态组合**：实测「生成一张火星基地概念图，写一段探险日记，再生成探险视频」
  单次任务串联 3 个 Agent、3 个不同模型，约 7 分钟产出三种产物。
- **能力感知路由**：路由不只看能力标签，还看请求形态——带图片输入的文本任务自动切换
  视觉语言模型（VLM），避免纯文本模型无法处理图片的协议错误。
- **模型降级与容错**：同类能力注册主备多个模型，失败自动切换；调用链完整记录
  每次降级（哪个角色、哪个模型、错误码、耗时），历史可回溯。
- **反思重试闭环**：每步产物即时送审，Reviewer 不通过时由 Orchestrator 依据
  审查意见重做该步骤；重试受预算约束（`max_retries`），从协议层杜绝死循环。
- **异构时长任务**：秒级文本任务与分钟级视频任务在同一编排体系下共存，
  视频走「异步提交 + 轮询」分支，带独立超时预算，前端显式提示长任务等待。
- **全链路可观测**：`/progress` 实时事件流 + `/agents` 调度轨迹 + `call_chain`
  模型级调用明细，三层可观测性数据均可通过 API 查询、前端可视化回放。

---

## 架构图

```
┌──────────────────────────────────────────────────────────────────────┐
│                     React 前端 (frontend/, Vite)                      │
│        会话管理 · 对话流 · Agent 角色卡 · 调用链路观测看板               │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ HTTP（轮询进度 / 结果，预留 SSE）
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        FastAPI 服务端 (src/api/)                      │
│                                                                      │
│  POST /api/task/submit ──→ Redis 队列 ──→ Worker 后台线程             │
│  GET  /api/task/{id}            │                                    │
│  GET  /api/task/{id}/progress ◄─┘ 实时进度事件流                      │
│  GET  /api/task/{id}/agents    ◄── 多 Agent 调度轨迹                  │
│  GET|POST /api/sessions · PATCH|DELETE /api/session/{id} 会话管理     │
└───────────────┬──────────────────────────┬──────────────────────────┘
                │                          │
       ┌────────▼────────┐        ┌────────▼────────────┐
       │   Redis 队列     │        │   SQLite (WAL)       │
       │ 任务队列/状态/    │        │ 会话/消息/任务日志/   │
       │ 进度事件/ID 映射  │        │ 审计记录/Agent 轨迹   │
       └─────────────────┘        └─────────────────────┘
                │
       ┌────────▼─────────────────────────────────────────────────┐
       │              Orchestrator (src/core/orchestrator.py)      │
       │   PLANNING → DISPATCHING → COLLECTING → AUDITING → 终态    │
       │   （反思重试闭环：审查打回 → 按预算重做该步骤）              │
       └───┬──────────┬──────────┬──────────┬─────────────────────┘
           ▼          ▼          ▼          ▼
     ┌─────────┐┌─────────┐┌─────────┐┌───────────────┐
     │ Writer  ││ Image   ││ Video   ││ Reviewer      │   ← BaseAgent 统一基类
     │ Agent   ││ Agent   ││ Agent   ││ Agent         │     （路由/降级/调用链托管）
     └────┬────┘└────┬────┘└────┬────┘└──────┬────────┘
          └──────────┴────┬─────┴────────────┘
                          ▼
       ┌─────────────────────────────────────────────────┐
       │   MessageBus（星型消息通道 + 轨迹落库）            │
       │   AgentRegistry（能力标签 → Agent 寻址）           │
       │   Router（能力标签 → 大模型，主备降级）             │
       │   LLMClient（HTTP / 异步视频分支）                 │
       └─────────────────────────────────────────────────┘
```

---

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+（前端）
- Redis（任务队列与进度通道）

### 1. 安装依赖

```bash
# 后端
pip install -r requirements.txt

# 前端
cd frontend && npm install
```

### 2. 配置模型

```bash
cp config/models.example.yaml config/model.yaml
```

编辑 `config/model.yaml`，将 `api_key` 替换为真实密钥。
默认对接 [硅基流动](https://cloud.siliconflow.cn)（文本/生图/视频一站式），
也兼容阿里云百炼 DashScope 协议：

```yaml
models:
  - registered_name: "writer-primary"          # 本地注册名（主备切换标识）
    model_name: "deepseek-ai/DeepSeek-V3"      # 平台真实模型标识
    endpoint: "https://api.siliconflow.cn/v1/chat/completions"
    api_key: "sk-xxxxxxxx"
    capability: "text-generation"              # 能力标签
```

同一平台（硅基流动）的模型共用一个 API Key 即可；
混合平台时按模型逐条配置各自的 Key。

### 3. 启动 Redis

```bash
redis-server
# 或常驻: brew services start redis
```

### 4. 启动后端（端口 8100）

```bash
uvicorn src.api.main:app --host 127.0.0.1 --port 8100 --reload
```

### 5. 启动前端（端口 1277）

```bash
cd frontend
npm run dev
```

浏览器访问 **http://localhost:1277**，输入自然语言指令即可。
视频生成任务耗时约 3-6 分钟，界面会显式提示等待。

### 切换单 Agent 基线（论文对比实验用）

```python
from src.api import create_agent
agent, storage = create_agent(multi_agent=False)   # 默认 True（多 Agent）
```

---

## API 端点

| 方法 | 路径 | 职责 |
|------|------|------|
| `POST` | `/api/task/submit` | 提交任务，返回 `task_id`（自动登记会话） |
| `GET` | `/api/task/{task_id}` | 查询任务状态与执行结果 |
| `GET` | `/api/task/{task_id}/progress` | 任务进度事件流（planning/dispatching/collecting/auditing，含 agent 维度） |
| `GET` | `/api/task/{task_id}/agents` | 多 Agent 调度轨迹（按步骤分组，含角色/产物/状态） |
| `GET` | `/api/sessions` | 获取全部会话列表 |
| `POST` | `/api/sessions` | 显式创建会话 |
| `GET` | `/api/session/{id}/history` | 获取对话消息与历史任务（含调用链） |
| `GET` | `/api/session/{id}/tasks` | 获取会话的进行中与已完成任务 |
| `PATCH` | `/api/session/{id}` | 重命名会话 |
| `DELETE` | `/api/session/{id}` | 删除整个会话（级联消息/日志/审计） |
| `DELETE` | `/api/session/{id}/history` | 仅清空会话消息与任务日志（保留会话） |

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 语言 | Python 3.10+ / TypeScript |
| 后端框架 | FastAPI |
| 任务队列 | Redis（队列 + 进度事件通道 + ID 映射） |
| 持久化 | SQLite（WAL 模式，含 agent_messages 协作轨迹表） |
| 前端 | React 18 + Vite + Tailwind CSS + Zustand |
| 模型平台 | 硅基流动（主）/ 阿里云百炼（兼容） |
| 可视化 | Lucide Icons，预留 React Flow |
| 测试 | pytest（78+ 用例） |

---

## 项目结构

```
src/
  core/                     # 核心引擎
    orchestrator.py         # 多 Agent 编排中枢（DISPATCHING→COLLECTING→AUDITING）
    registry.py             # AgentRegistry：能力标签 → Agent 寻址
    message_bus.py          # 星型消息总线（派发/回收/轨迹落库）
    contracts.py            # 多 Agent 契约（Artifact/AgentMessage/AgentResponse）
    base_agent.py           # Agent 基类（统一路由/降级/调用链托管）
    agents/                 # 专业 Agent
      writer_agent.py       #   文本生成（带图自动切 VLM）
      image_agent.py        #   文生图 / 图生图
      video_agent.py        #   文生视频 / 图生视频（异步长任务）
      reviewer_agent.py     #   两级审查（规则快筛 + LLM 深度评估）
    agent.py                # 旧单 Agent（保留作基线，multi_agent=False 时启用）
    task_router.py          # LLM 意图解析 → ExecutionPlan（capability 白名单约束）
    router.py               # 模型注册中心（能力匹配 + 标签别名归一化）
    llm_client.py           # 模型调用（同步文本/图片 + 异步视频分支）
    builder.py              # 拼装用户响应与调试日志
    memory.py               # 多轮对话上下文 + Agent 维度隔离
    storage.py              # SQLite 持久化（会话/消息/任务日志/审计/Agent 轨迹）
    models.py               # 数据模型（dataclass）
  api/                      # FastAPI 服务端
    main.py                 # API 路由与应用入口（含 CORS）
    redis_task_manager.py   # Redis 队列 + 进度通道 + 任务 ID 映射
    worker.py               # 后台消费者线程（含进度回调接线）
    task_manager.py         # 任务管理器抽象接口
  adapters/
    config.py               # YAML 配置加载
  ui/
    app.py                  # Streamlit 界面（历史版本，保留备用）
frontend/                   # React 前端（现役）
  src/api/                  #   HTTP 客户端（任务/会话）
  src/stores/               #   Zustand 状态（会话/任务）
  src/components/
    sidebar/                #   会话导航（创建/重命名/删除）
    chat/                   #   对话流 + Agent 角色卡
    inspector/              #   调用链路观测看板
config/
  model.yaml                # 实际模型配置（含密钥，不提交）
  models.example.yaml       # 模型配置模板
  app.example.yaml          # 应用配置模板（端口/轮询/超时）
docs/                       # 设计文档（升级计划/工单方案/技术复盘等）
tests/                      # pytest 测试用例
```

---

## 设计亮点

- **多 Agent 协作而非多模型调度**：Orchestrator 只做拆解、派发、聚合、仲裁；
  专业 Agent 各自封装领域 Prompt 与产物契约（Artifact）。调用链记录
  `agent` 角色名与 `elapsed_ms` 耗时——这是证明"多 Agent 协作"的直接证据，
  也是与"单 Agent 多模型调度器"的本质区别。

- **双层注册体系**：上层 `AgentRegistry`（能力 → Agent）供编排器寻址，
  下层 `Router`（能力 → 大模型）供 Agent 内部降级切换。
  两层解耦，Agent 替换不影响模型选型，模型扩容不触碰编排逻辑。

- **能力感知路由**：路由决策同时考虑能力标签与请求形态。
  带图文本任务自动改走 `image-to-text` VLM 模型池；未注册的能力标签
  经别名表归一化（如 `image-understanding → image-to-text`），
  从源头消灭"标签发明"导致的 NO_AVAILABLE_MODEL。

- **反思重试闭环（带防死循环预算）**：每步产物生成即送审，
  Reviewer 不通过时 Orchestrator 依据审查意见重做该步骤；
  `TaskContext.max_retries` 从协议层限制重试次数，超限降级交付（PARTIAL_SUCCESS）。

- **状态机驱动的编排**：`READY → PLANNING → DISPATCHING → COLLECTING →
  AUDITING → SUCCESS / PARTIAL_SUCCESS / FAILED`，每个状态职责单一，
  复杂调度逻辑可预测、易调试。

- **三层可观测性**：Orchestrator 事件流（`/progress`）→ Agent 消息轨迹
  （`/agents`，落库 `agent_messages`）→ 模型调用明细（`call_chain`，
  含角色/耗时/错误码）。三层均可 API 查询，前端观测看板可视化回放。

- **异构时长任务共存**：视频任务走独立的「异步提交 + 轮询」分支与
  10 分钟超时预算，与秒级文本任务在同一编排体系下协作；
  前端按输入意图自动切换超时预算并提示长任务等待。

- **面向用户与面向开发的双输出**：Builder 同时生成 `frontend_response`
  （面向用户，失败时隐藏内部错误码）和 `log_record`（完整调用链、
  时间戳、错误摘要），兼顾体验与排查效率。

---

## 文档

| 文档 | 内容 |
|------|------|
| [docs/毕设总方案.md](docs/毕设总方案.md) | 选题定位、目标架构、实验设计、论文结构 |
| [docs/升级计划.md](docs/升级计划.md) | 多 Agent 四阶段演进路线（已完成阶段含交付记录） |
| [docs/工单方案.md](docs/工单方案.md) | 剩余工作拆解为可独立验收的工单（T-01~T-10） |
| [docs/会话管理方案.md](docs/会话管理方案.md) | 会话生命周期与分层存储设计 |
| [docs/前端优化方案.md](docs/前端优化方案.md) | 前端从 Streamlit 到 React 的重构方案 |
| [docs/技术](docs/技术) | 已知局限与故障复盘（含根因与修复 diff） |

---

## 测试

```bash
uv run --with pytest --with pyyaml --with requests pytest tests/
```

当前 78+ 用例通过，覆盖：契约序列化往返、模型降级窗口、反思重试预算、
审查打回语义、Agent 记忆隔离、进度事件契约、会话生命周期。
