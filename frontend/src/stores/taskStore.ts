import { create } from 'zustand';
import { taskApi } from '../api/task';
import type { TaskDetail } from '../types';

interface TaskState {
  activeTaskId: string | null;
  isExecuting: boolean;
  currentTask: TaskDetail | null;
  taskHistory: TaskDetail[];
  error: string | null;

  submitTask: (userInput: string, sessionId: string) => Promise<TaskDetail | null>;
  setCurrentTask: (task: TaskDetail | null) => void;
  clearError: () => void;
}

export const useTaskStore = create<TaskState>((set) => ({
  activeTaskId: null,
  isExecuting: false,
  currentTask: null,
  taskHistory: [],
  error: null,

  submitTask: async (userInput: string, sessionId: string) => {
    set({ isExecuting: true, error: null });
    try {
      const res = await taskApi.submitTask(userInput, sessionId);
      const taskId = res.task_id;
      set({ activeTaskId: taskId });

      // 开始精准轮询，实时回传任务进展
      const completedTask = await taskApi.pollTaskUntilDone(
        taskId,
        (progressTask) => {
          set({ currentTask: progressTask });
        },
        800 // 800ms 轮询间隔
      );

      set((state) => ({
        currentTask: completedTask,
        activeTaskId: null,
        isExecuting: false,
        taskHistory: [completedTask, ...state.taskHistory.slice(0, 19)],
      }));

      return completedTask;
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : '任务执行失败';
      set({ error: errMsg, isExecuting: false, activeTaskId: null });
      return null;
    }
  },

  setCurrentTask: (task: TaskDetail | null) => {
    set({ currentTask: task });
  },

  clearError: () => {
    set({ error: null });
  },
}));
