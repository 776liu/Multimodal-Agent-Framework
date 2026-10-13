import { apiClient } from './client';
import type { SessionInfo, SessionHistoryResponse, SessionTasksResponse } from '../types';

export const sessionApi = {
  // 获取所有会话列表
  listSessions: async (): Promise<SessionInfo[]> => {
    const res = await apiClient.get<{ sessions: SessionInfo[] }>('/sessions');
    return res.data.sessions || [];
  },

  // 显式创建会话（后端登记到 sessions 表）
  createSession: async (label: string = '新对话'): Promise<SessionInfo> => {
    const res = await apiClient.post<SessionInfo>('/sessions', { label });
    return res.data;
  },

  // 重命名会话
  renameSession: async (sessionId: string, label: string): Promise<void> => {
    await apiClient.patch(`/session/${sessionId}`, { label });
  },

  // 删除整个会话（级联消息/任务日志/审计/在途任务）
  deleteSession: async (sessionId: string): Promise<void> => {
    await apiClient.delete(`/session/${sessionId}`);
  },

  // 获取单个会话的完整历史（含对话与任务）
  getSessionHistory: async (sessionId: string): Promise<SessionHistoryResponse> => {
    const res = await apiClient.get<SessionHistoryResponse>(`/session/${sessionId}/history`);
    return res.data;
  },

  // 获取会话下的任务列表
  getSessionTasks: async (sessionId: string): Promise<SessionTasksResponse> => {
    const res = await apiClient.get<SessionTasksResponse>(`/session/${sessionId}/tasks`);
    return res.data;
  },

  // 清空会话历史（保留会话本身）
  deleteSessionHistory: async (sessionId: string): Promise<void> => {
    await apiClient.delete(`/session/${sessionId}/history`);
  },
};
