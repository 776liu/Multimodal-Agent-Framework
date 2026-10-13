import { create } from 'zustand';
import { sessionApi } from '../api/session';
import type { SessionInfo, MessageItem, CallChainEntry } from '../types';

/** 会话内单条任务的历史视图（供观测看板回放调用链） */
export interface SessionTaskHistoryItem {
  task_id: string;
  task_status: string;
  created_at?: string;
  user_input?: string;
  call_chain?: CallChainEntry[];
  error_summary?: Array<{ model_name: string; capability: string; error_code?: number | null }>;
}

interface SessionState {
  sessions: SessionInfo[];
  currentSessionId: string;
  messages: MessageItem[];
  sessionTasks: SessionTaskHistoryItem[];
  isLoadingSessions: boolean;
  isLoadingHistory: boolean;

  loadSessions: () => Promise<void>;
  selectSession: (sessionId: string) => Promise<void>;
  createNewSession: () => Promise<void>;
  renameSession: (sessionId: string, label: string) => Promise<void>;
  deleteSession: (sessionId: string) => Promise<void>;
  clearHistory: () => Promise<void>;
  addMessage: (message: MessageItem) => void;
  refreshSessionLabel: (sessionId?: string) => Promise<void>;
}

export const useSessionStore = create<SessionState>((set, get) => ({
  sessions: [],
  currentSessionId: 'default',
  messages: [],
  sessionTasks: [],
  isLoadingSessions: false,
  isLoadingHistory: false,

  loadSessions: async () => {
    set({ isLoadingSessions: true });
    try {
      const list = await sessionApi.listSessions();
      set({ sessions: list });

      // 如果当前 session 不在列表且列表非空，默认选中第一个
      const current = get().currentSessionId;
      if (list.length > 0 && !list.find((s) => s.session_id === current)) {
        await get().selectSession(list[0].session_id);
      } else if (list.length === 0) {
        await get().selectSession('default');
      } else {
        await get().selectSession(current);
      }
    } catch (err) {
      console.error('Failed to load sessions:', err);
    } finally {
      set({ isLoadingSessions: false });
    }
  },

  selectSession: async (sessionId: string) => {
    set({ currentSessionId: sessionId, isLoadingHistory: true });
    try {
      const history = await sessionApi.getSessionHistory(sessionId);
      set({
        messages: history.messages || [],
        // 切换会话时重建该会话的任务调用链历史（观测看板回放数据源）
        sessionTasks: history.tasks || [],
      });
    } catch (err) {
      console.error(`Failed to load history for session ${sessionId}:`, err);
      set({ messages: [], sessionTasks: [] });
    } finally {
      set({ isLoadingHistory: false });
    }
  },

  // 新建会话：先在后端 sessions 表登记，成功后再入列（刷新不丢失）
  createNewSession: async () => {
    try {
      const created = await sessionApi.createSession('新对话');
      set((state) => ({
        sessions: [created, ...state.sessions],
        currentSessionId: created.session_id,
        messages: [],
      }));
    } catch (err) {
      console.error('Failed to create session:', err);
      // 兜底：后端异常时退回本地创建，保证交互不中断
      const newId = `session_${Date.now()}`;
      set((state) => ({
        sessions: [
          { session_id: newId, label: '新对话', created_at: new Date().toISOString() },
          ...state.sessions,
        ],
        currentSessionId: newId,
        messages: [],
      }));
    }
  },

  // 重命名会话：更新后端并同步本地列表
  renameSession: async (sessionId: string, label: string) => {
    const trimmed = label.trim();
    if (!trimmed) return;
    try {
      await sessionApi.renameSession(sessionId, trimmed);
      set((state) => ({
        sessions: state.sessions.map((s) =>
          s.session_id === sessionId ? { ...s, label: trimmed } : s
        ),
      }));
    } catch (err) {
      console.error('Failed to rename session:', err);
    }
  },

  // 删除整个会话：级联后端数据并从列表移除；若删的是当前会话则切到第一个
  deleteSession: async (sessionId: string) => {
    try {
      await sessionApi.deleteSession(sessionId);
      const remaining = get().sessions.filter((s) => s.session_id !== sessionId);
      set((state) => ({
        sessions: remaining,
        currentSessionId:
          state.currentSessionId === sessionId
            ? remaining[0]?.session_id ?? 'default'
            : state.currentSessionId,
      }));
      // 若当前会话被删，加载新会话的历史
      if (get().currentSessionId !== sessionId) {
        await get().selectSession(get().currentSessionId);
      } else {
        set({ messages: [] });
      }
    } catch (err) {
      console.error('Failed to delete session:', err);
    }
  },

  clearHistory: async () => {
    const { currentSessionId } = get();
    try {
      await sessionApi.deleteSessionHistory(currentSessionId);
      set({ messages: [] });
    } catch (err) {
      console.error('Failed to delete session history:', err);
    }
  },

  addMessage: (message: MessageItem) => {
    set((state) => ({
      messages: [...state.messages, message],
    }));
  },

  // 任务完成后刷新当前会话标签（Worker 可能已用首条消息回填）
  refreshSessionLabel: async (_sessionId?: string) => {
    try {
      const list = await sessionApi.listSessions();
      set({ sessions: list });
    } catch (err) {
      console.error('Failed to refresh session label:', err);
    }
  },
}));
