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
  status: 'SUCCESS' | 'FAILED' | string;
  error_code?: number | null;
  attempted_at?: string;
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
  tasks: Array<Record<string, unknown>>;
}

export interface SessionTasksResponse {
  session_id: string;
  processing: Array<{ task_id: string; status: string; user_input: string }>;
  completed: Array<{ task_id: string; final_status: string; user_input: string }>;
}
