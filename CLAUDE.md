# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 文档语言规定

**所有文档（包括 CLAUDE.md、需求文档、模块说明、注释中的长段说明、README、commit message）均使用中文书写。** 代码标识符（变量名、函数名、类名、模块名）使用英文。

## 项目概述

多模态 Agent 框架（Multimodal Agent Framework）—— 一个 Python AI Agent 编排系统。接收用户的自然语言输入，将其拆解为子任务（文本生成、图片生成），为每个子任务匹配最合适的大模型并自动执行降级切换，最终拼装统一的 JSON 响应返回给前端。底层对接阿里云百炼模型。

## 架构

系统由五个核心模块组成管线，由 Agent 状态机统一驱动：

```
[用户输入] → Agent（状态机总控）
               ├─ TaskRouter（意图解析 → 生成执行计划）
               ├─ Router（模型注册中心 + 能力匹配）
               ├─ llmClient（无状态 HTTP 调用，对接模型端点）
               └─ Builder（拼装前端响应 + 日志记录）
```

### 各模块职责

- **Agent**（`src/core/`）：总控制器。驱动状态机流转：`READY → PLANNING → ROUTING → CALLING → SUCCESS/PARTIAL_SUCCESS/FAILED/DEAD`。协调所有其他模块的调用顺序。
- **TaskRouter**（`src/core/`）：解析用户意图，拆解为 `ExecutionPlan`—— 包含有序的 `Subtask` 列表，每个子任务含 `step`（步骤序号）、`capability`（所需模型能力）、`prompt`（生成提示词）。无法识别意图时返回 `INTENT_PARSE_FAILED`。
- **Router**（`src/core/`）：模型注册中心。根据 `capability` 字符串返回优先级最高的可用模型连接信息（`model_name`、`endpoint`、`api_key`）。重试时排除已失败的模型，所有模型耗尽时返回 `NO_AVAILABLE_MODEL`。
- **llmClient**（`src/adapters/`）：无状态 HTTP 调用器。接收模型连接信息 + prompt，返回标准化的 `{status, data}` 或 `{status, error_code, model_name}`。默认超时 30 秒。**不负责重试或降级逻辑**，每次调用独立返回结果。
- **Builder**（`src/core/`）：接收原始子任务结果 + 调用链，生成两份 JSON 输出：`frontend_response`（面向用户，失败时隐藏内部错误码）和 `log_record`（完整调用链，含错误码和 error_summary，用于调试）。

### 数据模型

详见 [src/core/models.py](src/core/models.py)，定义了 `ModelInfo`、`Subtask`、`ExecutionPlan`、`llmResponse` 四个 dataclass。

### 状态机流转

- `READY`：接收用户输入，生成 `task_id`，转入 `PLANNING`
- `PLANNING`：调用 TaskRouter；成功 → `ROUTING`，失败 → `FAILED`
- `ROUTING`：调用 Router，传入 capability；成功 → `CALLING`，`NO_AVAILABLE_MODEL` → `FAILED`
- `CALLING`：调用 llmClient；成功则检查是否还有剩余子任务（有 → 回到 `ROUTING`，无 → `SUCCESS`）；失败则尝试备选模型（有备选 → 回到 `ROUTING` 并传递失败模型列表，无备选 → 检查是否有已成功的子任务：有 → `PARTIAL_SUCCESS`，无 → `FAILED`）
- 终态：`SUCCESS`、`PARTIAL_SUCCESS`（至少一个子任务成功 + 至少一个子任务所有备选耗尽）、`FAILED`（所有子任务全部耗尽）

### 已注册模型

| 注册名 | 能力标签 | 百炼模型 | 过期时间 |
|--------|---------|---------|---------|
| qwen-plus | text-generation | qwen3.7-plus | 2026-09-01 |
| qwen-max | text-generation | qwen3.7-max-2026-06-08 | 2026-09-08 |
| qwen-image | image-generation | qwen-image-2.0-pro | 2026-07-23 |
| wan2.7 | image-generation | wan2.7-image-pro | 2026-07-01 |

### 错误码表

| 错误码 | 含义 | 发生位置 | 处理策略 | 处理模块 |
|--------|------|---------|---------|---------|
| 503 | 服务不可用 | llmClient | 切换备选模型 | Router |
| 401 | Key 错误 | llmClient | 切换备选模型 | Router |
| TIMEOUT | 调用超时 | llmClient | 切换备选模型 | Router |
| INTENT_PARSE_FAILED | 意图识别失败 | TaskRouter | 返回失败，提示更换提示词 | Agent |
| NO_AVAILABLE_MODEL | 无可用模型 | Router | 任务失败，返回用户提示 | Agent |
| ALL_MODELS_EXHAUSTED | 所有模型耗尽 | Agent | 任务失败，返回用户提示 | Agent |

## 项目规范

### 配置文件

- 配置格式：YAML（`config/dev.yaml`、`config/prod.yaml`）
- 通过环境变量 `ENV` 切换环境
- Agent 启动后、进入 `READY` 状态前，对已注册模型执行 `health_check`（发送最轻量请求验证 endpoint 可达、api_key 有效），校验失败的模型标记为 unavailable 但不阻断启动
- **严禁**在代码中硬编码 `endpoint` 和 `api_key`

### 目录结构

```
src/
  core/       # Agent、TaskRouter、Router、Builder、models
  adapters/   # llmClient（外部服务适配器）
  ui/         # 前端/展示层（规划中）
config/       # dev.yaml、prod.yaml
tests/        # 测试用例
docs/         # 需求和模块规格说明
```

### 命名约定

- 模块名、类名、函数名、变量名使用英文
- 需求和文档使用中文
- 数据模型字段使用 snake_case

### 响应格式

无论成功/失败/部分成功，每次响应均包含两部分：
- `frontend_response`：面向用户，失败时屏蔽内部错误细节，仅返回可读提示
- `log_record`：含完整调用链（时间戳、错误码、`error_summary`），供开发调试
