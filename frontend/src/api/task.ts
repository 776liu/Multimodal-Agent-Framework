import { apiClient } from './client';
import type { TaskDetail } from '../types';

export const taskApi = {
  // 提交任务
  submitTask: async (
    userInput: string,
    sessionId: string = 'default'
  ): Promise<{ task_id: string; status: string }> => {
    const res = await apiClient.post<{ task_id: string; status: string }>(
      '/task/submit',
      {
        user_input: userInput,
        session_id: sessionId,
      }
    );
    return res.data;
  },

  // 获取任务状态详情
  getTask: async (taskId: string): Promise<TaskDetail> => {
    const res = await apiClient.get<TaskDetail>(`/task/${taskId}`);
    return res.data;
  },

  // 轮询等待任务完成（在 SSE 完全打通前提供无缝兼容的高精度轮询）
  pollTaskUntilDone: async (
    taskId: string,
    onProgress?: (task: TaskDetail) => void,
    intervalMs: number = 1000,
    timeoutMs: number = 120000
  ): Promise<TaskDetail> => {
    const startTime = Date.now();

    while (Date.now() - startTime < timeoutMs) {
      const task = await taskApi.getTask(taskId);
      if (onProgress) {
        onProgress(task);
      }

      const status = task.status;
      if (
        status === 'SUCCESS' ||
        status === 'PARTIAL_SUCCESS' ||
        status === 'FAILED' ||
        status === 'completed' ||
        status === 'failed'
      ) {
        return task;
      }

      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }

    throw new Error('Task polling timed out');
  },
};
