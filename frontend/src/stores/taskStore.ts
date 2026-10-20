import { create } from 'zustand';
import { taskApi } from '../api/task';
import type { TaskDetail, ProgressEvent, AgentTraceResponse } from '../types';

/**
 * 任务超时预算分层：
 *  - 普通文本/图片任务：8 分钟（正常秒级完成，留足降级重试余量）
 *  - 视频生成任务：20 分钟（平台实测队列2min + 推理3.5min，多步任务需叠加）
 * 判定依据：用户输入含视频意图关键词时按长任务预算处理，
 * 避免"前端先放弃、后台仍在跑"的任务失联问题。
 */
const TIMEOUT_TEXT_MS = 8 * 60 * 1000;
const TIMEOUT_VIDEO_MS = 20 * 60 * 1000;

const VIDEO_HINT_RE = /视频|短片|动画|影片|动画片段|剪辑|分镜视频|video|动画效果/i;

function resolveTimeoutMs(userInput: string): number {
  return VIDEO_HINT_RE.test(userInput) ? TIMEOUT_VIDEO_MS : TIMEOUT_TEXT_MS;
}

interface TaskState {
  activeTaskId: string | null;
  isExecuting: boolean;
  currentTask: TaskDetail | null;
  taskHistory: TaskDetail[];
  error: string | null;
  /** 已等待时长（毫秒），供 UI 展示"已等待 x 分 y 秒" */
  elapsedMs: number;
  /** 实时进度事件（工单 T-01）：轮询过程中增量拉取，供角色卡逐节点点亮 */
  progressEvents: ProgressEvent[];
  /** 多 Agent 调度轨迹（工单 T-01）：任务终态后一次性拉取，用于渲染协作视图 */
  agentTrace: AgentTraceResponse | null;

  submitTask: (userInput: string, sessionId: string) => Promise<TaskDetail | null>;
  setCurrentTask: (task: TaskDetail | null) => void;
  clearError: () => void;
  /** 按 taskId 拉取某次任务的调度轨迹（供历史回放复用） */
  loadAgentTrace: (taskId: string) => Promise<void>;
}

export const useTaskStore = create<TaskState>((set) => ({
  activeTaskId: null,
  isExecuting: false,
  currentTask: null,
  taskHistory: [],
  error: null,
  elapsedMs: 0,
  progressEvents: [],
  agentTrace: null,

  submitTask: async (userInput: string, sessionId: string) => {
    set({ isExecuting: true, error: null, elapsedMs: 0, progressEvents: [], agentTrace: null });
    const startedAt = Date.now();
    // 增量拉取进度事件已消费的条数，避免重复累积
    let consumedEvents = 0;
    try {
      const res = await taskApi.submitTask(userInput, sessionId);
      const taskId = res.task_id;
      set({ activeTaskId: taskId });

      // 视频类任务使用更长预算，其余走默认预算
      const completedTask = await taskApi.pollTaskUntilDone(
        taskId,
        async (progressTask: TaskDetail) => {
          set({ currentTask: progressTask, elapsedMs: Date.now() - startedAt });
          // 增量拉取进度事件（工单 T-01）：失败静默，不影响任务轮询
          try {
            const events = await taskApi.getProgress(taskId);
            if (events.length > consumedEvents) {
              consumedEvents = events.length;
              set({ progressEvents: events });
            }
          } catch {
            /* 进度事件不可用时降级为纯轮询 */
          }
        },
        2000, // 2s 轮询间隔（视频任务下可降低请求频率）
        resolveTimeoutMs(userInput)
      );

      // 终态后补齐：完整事件序列 + 多 Agent 调度轨迹
      let trace: AgentTraceResponse | null = null;
      try {
        const events = await taskApi.getProgress(taskId);
        if (events.length > 0) set({ progressEvents: events });
        trace = await taskApi.getAgents(taskId);
      } catch {
        /* 轨迹接口异常时保持已有数据 */
      }

      set((state) => ({
        currentTask: completedTask,
        activeTaskId: null,
        isExecuting: false,
        elapsedMs: Date.now() - startedAt,
        agentTrace: trace ?? state.agentTrace,
        taskHistory: [completedTask, ...state.taskHistory.slice(0, 19)],
      }));

      return completedTask;
    } catch (err: unknown) {
      const isTimeout = err instanceof Error && err.message.includes('timed out');
      const errMsg = isTimeout
        ? '前端等待超时，但后台任务可能仍在继续执行，请稍后刷新会话查看结果'
        : err instanceof Error
        ? err.message
        : '任务执行失败';
      set({
        error: errMsg,
        isExecuting: false,
        activeTaskId: null,
        elapsedMs: Date.now() - startedAt,
      });
      return null;
    }
  },

  setCurrentTask: (task: TaskDetail | null) => {
    set({ currentTask: task });
  },

  loadAgentTrace: async (taskId: string) => {
    try {
      const [events, trace] = await Promise.all([
        taskApi.getProgress(taskId),
        taskApi.getAgents(taskId),
      ]);
      set({ progressEvents: events, agentTrace: trace });
    } catch (err) {
      console.error('Failed to load agent trace:', err);
    }
  },

  clearError: () => {
    set({ error: null });
  },
}));
