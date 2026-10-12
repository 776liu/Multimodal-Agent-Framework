import { apiClient } from './client';
import type { SessionInfo, SessionHistoryResponse, SessionTasksResponse } from '../types';

export const sessionApi = {
  // 获取所有会话列表
  listSessions: async (): Promise<SessionInfo[]> => {
    const res = await apiClient.get<{ sessions: SessionInfo[] }>('/sessions');
    return res.data.sessions || [];
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

  // 清空会话历史
  deleteSessionHistory: async (sessionId: string): Promise<void> => {
    await apiClient.delete(`/session/${sessionId}/history`);
  },
};
