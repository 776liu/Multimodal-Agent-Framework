export type TaskStatus =
  | 'pending'
  | 'processing'
  | 'SUCCESS'
  | 'PARTIAL_SUCCESS'
  | 'FAILED';

export interface TaskResultItem {
  type: 'text' | 'image' | string;
  url?: string | null;
  content?: string | null;
}

export interface CallChainEntry {
  model_name: string;
  capability: string;
  status: 'SUCCESS' | 'FAILED' | 'NEED_REVISION' | string;
  error_code?: number | null;
  attempted_at?: string;
  /** 发起该调用的 Agent 角色名（工单 T-01）。老数据缺此字段时为空串 */
  agent?: string;
  /** 本次模型调用耗时（毫秒）。老数据缺此字段时为 0 */
  elapsed_ms?: number;
}

/** 任务进度事件（工单 T-01 /progress 端点） */
export interface ProgressEvent {
  stage:
    | 'planning'
    | 'planned'
    | 'dispatching'
    | 'collecting'
    | 'auditing'
    | 'revision'
    | string;
  agent?: string;
  step?: number;
  total?: number;
  status?: string;
  issues?: string[];
  notice?: string;
  ts?: number;
}

/** /agents 端点：一条 Agent 间消息（工单 T-01） */
export interface AgentTraceEntry {
  from_agent: string;
  to_agent: string;
  message_type: 'dispatch' | 'result' | string;
  status?: string | null;
  content?: string;
  artifacts?: Array<{ type: string; url: string }>;
  created_at?: string;
}

export interface AgentTraceStep {
  step: number;
  entries: AgentTraceEntry[];
}

export interface AgentTraceResponse {
  task_id: string;
  internal_task_id: string;
  roles: string[];
  steps: AgentTraceStep[];
  message_count: number;
}

export interface TaskResponseData {
  results?: TaskResultItem[];
  type?: string;
  message?: string;
}

export interface FrontendResponse {
  task_id: string;
  task_status: TaskStatus;
  system_status?: string;
  data: TaskResponseData;
}

export interface LogRecord {
  task_id: string;
  timestamp?: string;
  task_status: TaskStatus;
  call_chain: CallChainEntry[];
  error_summary?: Array<{
    model_name: string;
    capability: string;
    error_code?: number | null;
  }>;
}

export interface TaskDetail {
  task_id: string;
  status: TaskStatus | string;
  user_input: string;
  session_id: string;
  created_at?: string;
  result?: {
    frontend_response?: FrontendResponse;
    log_record?: LogRecord;
    error?: string;
  } | null;
}

export interface MessageItem {
  id?: number;
  session_id?: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at?: string;
}

export interface SessionInfo {
  session_id: string;
  label: string;
  created_at?: string;
}

export interface SessionHistoryResponse {
  session_id: string;
  messages: MessageItem[];
  tasks: Array<{
    task_id: string;
    task_status: string;
    created_at?: string;
    user_input?: string;
    summary?: TaskResultItem[];
    call_chain?: CallChainEntry[];
    error_summary?: Array<{ model_name: string; capability: string; error_code?: number | null }>;
  }>;
}

export interface SessionTasksResponse {
  session_id: string;
  processing: Array<{ task_id: string; status: string; user_input: string }>;
  completed: Array<{ task_id: string; final_status: string; user_input: string }>;
}
