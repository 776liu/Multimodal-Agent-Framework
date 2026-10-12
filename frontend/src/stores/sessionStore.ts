import { create } from 'zustand';
import { sessionApi } from '../api/session';
import type { SessionInfo, MessageItem } from '../types';

interface SessionState {
  sessions: SessionInfo[];
  currentSessionId: string;
  messages: MessageItem[];
  isLoadingSessions: boolean;
  isLoadingHistory: boolean;

  loadSessions: () => Promise<void>;
  selectSession: (sessionId: string) => Promise<void>;
  createNewSession: () => void;
  clearHistory: () => Promise<void>;
  addMessage: (message: MessageItem) => void;
}

export const useSessionStore = create<SessionState>((set, get) => ({
  sessions: [],
  currentSessionId: 'default',
  messages: [],
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
      set({ messages: history.messages || [] });
    } catch (err) {
      console.error(`Failed to load history for session ${sessionId}:`, err);
      set({ messages: [] });
    } finally {
      set({ isLoadingHistory: false });
    }
  },

  createNewSession: () => {
    const newId = `session_${Date.now()}`;
    const newSession: SessionInfo = {
      session_id: newId,
      label: '新对话',
      created_at: new Date().toISOString(),
    };
    set((state) => ({
      sessions: [newSession, ...state.sessions],
      currentSessionId: newId,
      messages: [],
    }));
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
}));
