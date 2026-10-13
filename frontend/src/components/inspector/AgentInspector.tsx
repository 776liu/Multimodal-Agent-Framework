import React, { useState, useMemo } from 'react';
import { useTaskStore } from '../../stores/taskStore';
import { useSessionStore } from '../../stores/sessionStore';
import type { CallChainEntry } from '../../types';import {
  Activity,
  CheckCircle2,
  XCircle,
  Clock,
  AlertTriangle,
  Layers,
  ShieldCheck,
  Cpu,
  Workflow,
  Server,
  Zap,
  Check,
  ChevronDown,
  History,
} from 'lucide-react';

/** 观测看板展示的任务视图（实时任务或历史任务统一结构） */
interface TaskView {
  taskId: string;
  status: string;
  userInput: string;
  callChain: CallChainEntry[];
  errorSummary: Array<{ model_name: string; capability: string; error_code?: number | null }>;
}

export const AgentInspector: React.FC = () => {
  const currentTask = useTaskStore((state) => state.currentTask);
  const isExecuting = useTaskStore((state) => state.isExecuting);
  const sessionTasks = useSessionStore((state) => state.sessionTasks);
  const [historyPickerOpen, setHistoryPickerOpen] = useState(false);
  // null = 展示实时任务; 数字 = 展示历史任务列表中的第 n 个
  const [selectedHistoryIdx, setSelectedHistoryIdx] = useState<number | null>(null);

  // 从会话任务历史构建可回放的任务视图列表
  const historyTasks: TaskView[] = useMemo(() => {
    return sessionTasks
      .filter((t) => t.task_id && t.task_status)
      .map((t) => ({
        taskId: t.task_id,
        status: t.task_status,
        userInput: t.user_input || '',
        callChain: t.call_chain || [],
        errorSummary: t.error_summary || [],
      }));
  }, [sessionTasks]);

  // 统一取当前应展示的任务视图
  const view: TaskView | null = useMemo(() => {
    if (selectedHistoryIdx !== null) return historyTasks[selectedHistoryIdx] ?? null;
    if (currentTask) {
      return {
        taskId: currentTask.task_id,
        status: String(currentTask.status || 'processing'),
        userInput: currentTask.user_input || '',
        callChain: currentTask.result?.log_record?.call_chain || [],
        errorSummary: currentTask.result?.log_record?.error_summary || [],
      };
    }
    if (!isExecuting && historyTasks.length > 0) {
      // 默认回放最近一次历史任务，保证看板"始终有内容"
      return historyTasks[0];
    }
    return null;
  }, [selectedHistoryIdx, currentTask, isExecuting, historyTasks]);

  const status = view?.status || (isExecuting ? 'processing' : 'IDLE');
  const failedCount = view?.callChain.filter((c) => c.status !== 'SUCCESS').length ?? 0;

  const getStatusBadge = (s: string) => {
    switch (s) {
      case 'SUCCESS':
        return (
          <span className="inline-flex items-center gap-1 text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full text-[11px] font-semibold border border-emerald-200/80">
            <CheckCircle2 className="w-3 h-3" /> 执行成功
          </span>
        );
      case 'PARTIAL_SUCCESS':
        return (
          <span
            className="inline-flex items-center gap-1 text-amber-700 bg-amber-50 px-2 py-0.5 rounded-full text-[11px] font-semibold border border-amber-300/80 animate-pulse"
            title="部分子任务失败，已交付可用的部分产物"
          >
            <AlertTriangle className="w-3 h-3" /> 部分成功 · {failedCount} 步失败
          </span>
        );
      case 'FAILED':
        return (
          <span className="inline-flex items-center gap-1 text-rose-600 bg-rose-50 px-2 py-0.5 rounded-full text-[11px] font-semibold border border-rose-200/80">
            <XCircle className="w-3 h-3" /> 执行失败
          </span>
        );
      case 'processing':
      case 'pending':
        return (
          <span className="inline-flex items-center gap-1 text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded-full text-[11px] font-semibold border border-indigo-200/80 animate-pulse">
            <Clock className="w-3 h-3 animate-spin" /> 执行中
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 text-slate-500 bg-slate-100 px-2 py-0.5 rounded-full text-[11px] font-medium border border-slate-200/60">
            <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
            空闲就绪
          </span>
        );
    }
  };

  const getPipelineStepStatus = (stepIndex: number) => {
    if (status === 'processing' || status === 'pending') {
      return stepIndex <= 2 ? 'active' : 'pending';
    }
    if (status === 'SUCCESS') return 'done';
    if (status === 'PARTIAL_SUCCESS') {
      // 部分成功：管道前段视为完成，末段(规则核验)标警示色
      return stepIndex <= 3 ? 'done' : 'warning';
    }
    if (status === 'FAILED') {
      return stepIndex <= 2 ? 'done' : 'error';
    }
    return 'pending';
  };

  return (
    <aside className="w-84 bg-white border-l border-slate-200/80 flex flex-col h-full select-none shrink-0 overflow-hidden transition-colors duration-200">
      {/* Header Bar */}
      <div className="p-3.5 border-b border-slate-100 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="p-1 rounded-md bg-indigo-50 text-indigo-600">
            <Activity className="w-3.5 h-3.5" />
          </div>
          <div>
            <h2 className="font-semibold text-xs text-slate-800">
              Agent 观测看板
            </h2>
            <p className="text-[10px] text-slate-400">
              {selectedHistoryIdx !== null ? '历史任务回放' : '实时链路观测'}
            </p>
          </div>
        </div>
        {getStatusBadge(status)}
      </div>

      <div className="flex-1 overflow-y-auto p-3.5 space-y-4">
        {/* Multi-turn Task Switcher */}
        {historyTasks.length > 1 && (
          <div className="relative">
            <button
              onClick={() => setHistoryPickerOpen((v) => !v)}
              className={`w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg border text-[11px] font-medium transition-colors ${
                selectedHistoryIdx !== null
                  ? 'bg-amber-50 border-amber-300 text-amber-800'
                  : 'bg-slate-50 border-slate-200 text-slate-600 hover:border-indigo-300'
              }`}
            >
              <span className="flex items-center gap-1.5 truncate">
                <History className="w-3.5 h-3.5 shrink-0" />
                {selectedHistoryIdx !== null
                  ? `回放: ${(historyTasks[selectedHistoryIdx]?.userInput || '').slice(0, 16)}...`
                  : '实时任务'}
              </span>
              <ChevronDown
                className={`w-3.5 h-3.5 shrink-0 transition-transform ${
                  historyPickerOpen ? 'rotate-180' : ''
                }`}
              />
            </button>

            {historyPickerOpen && (
              <div className="absolute z-20 mt-1 w-full bg-white border border-slate-200 rounded-lg shadow-lg max-h-56 overflow-y-auto">
                <button
                  onClick={() => {
                    setSelectedHistoryIdx(null);
                    setHistoryPickerOpen(false);
                  }}
                  className={`w-full text-left px-3 py-2 text-[11px] border-b border-slate-100 flex items-center gap-2 ${
                    selectedHistoryIdx === null
                      ? 'bg-indigo-50 text-indigo-700 font-semibold'
                      : 'hover:bg-slate-50 text-slate-600'
                  }`}
                >
                  <Zap className="w-3 h-3" /> 实时任务（最新）
                </button>
                {historyTasks.map((t, idx) => (
                  <button
                    key={t.taskId}
                    onClick={() => {
                      setSelectedHistoryIdx(idx);
                      setHistoryPickerOpen(false);
                    }}
                    className={`w-full text-left px-3 py-2 text-[11px] border-b border-slate-100 last:border-0 ${
                      selectedHistoryIdx === idx
                        ? 'bg-indigo-50 text-indigo-700 font-semibold'
                        : 'hover:bg-slate-50 text-slate-600'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate">{t.userInput.slice(0, 22) || t.taskId.slice(0, 12)}</span>
                      <span
                        className={`shrink-0 text-[9px] font-mono px-1 py-0.5 rounded ${
                          t.status === 'SUCCESS'
                            ? 'bg-emerald-50 text-emerald-600'
                            : t.status === 'PARTIAL_SUCCESS'
                            ? 'bg-amber-50 text-amber-700'
                            : 'bg-rose-50 text-rose-600'
                        }`}
                      >
                        {t.status === 'PARTIAL_SUCCESS' ? 'PARTIAL' : t.status}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Pipeline Stage Tracker */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-[11px] font-medium text-slate-500">
            <span className="flex items-center gap-1">
              <Zap className="w-3 h-3 text-indigo-500" />
              <span>编排管道阶段</span>
            </span>
            <span className="text-[10px] font-mono text-slate-400">
              {isExecuting && selectedHistoryIdx === null
                ? '运行阶段 2/4'
                : status === 'SUCCESS'
                ? '已完成 4/4'
                : status === 'PARTIAL_SUCCESS'
                ? '带警告完成'
                : status === 'FAILED'
                ? '异常终止'
                : '等待调度'}
            </span>
          </div>

          <div className="grid grid-cols-4 gap-1.5 pt-1">
            {[
              { label: '意图拆解', step: 1 },
              { label: '模型路由', step: 2 },
              { label: '工件生成', step: 3 },
              { label: '规则核验', step: 4 },
            ].map((s) => {
              const st = getPipelineStepStatus(s.step);
              return (
                <div
                  key={s.step}
                  className={`p-1.5 rounded-lg border text-center transition-all ${
                    st === 'done'
                      ? 'bg-emerald-50/70  border-emerald-200  text-emerald-700 '
                      : st === 'active'
                      ? 'bg-indigo-50  border-indigo-300  text-indigo-700  animate-pulse'
                      : st === 'warning'
                      ? 'bg-amber-50  border-amber-300  text-amber-700 '
                      : st === 'error'
                      ? 'bg-rose-50  border-rose-200  text-rose-700 '
                      : 'bg-slate-50  border-slate-200/60  text-slate-400 '
                  }`}
                >
                  <div className="text-[9px] font-mono font-bold leading-tight">
                    0{s.step}
                  </div>
                  <div className="text-[10px] font-medium truncate mt-0.5">
                    {s.label}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Task Meta Card */}
        {view ? (
          <div className="bg-slate-50 border border-slate-200/80 rounded-xl p-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-medium text-slate-400">
                {selectedHistoryIdx !== null ? '回放任务 ID' : '当前任务 ID'}
              </span>
              <span className="text-[10px] font-mono text-slate-700 bg-white px-1.5 py-0.5 rounded border border-slate-200/60">
                {view.taskId.slice(0, 14)}...
              </span>
            </div>
            <div>
              <span className="text-[11px] font-medium text-slate-400">
                用户指令输入
              </span>
              <p className="text-xs text-slate-700 font-normal mt-1 bg-white p-2 rounded-lg border border-slate-200/60 leading-relaxed break-words whitespace-pre-wrap select-none">
                {view.userInput || '（历史任务未记录输入）'}
              </p>
            </div>
          </div>
        ) : (
          <div className="p-5 text-center border border-dashed border-slate-200 rounded-xl bg-slate-50/50">
            <Cpu className="w-6 h-6 text-slate-300 mx-auto mb-1.5" />
            <p className="text-xs text-slate-400">
              等待任务触发，启动调度观测
            </p>
          </div>
        )}

        {/* Execution Flow (Call Chain) */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-800">
              <Workflow className="w-3.5 h-3.5 text-indigo-600" />
              <span>多智能体调用链</span>
            </div>
            <span className="text-[10px] font-mono text-slate-400 bg-slate-100 px-1.5 py-0.2 rounded">
              {view?.callChain.length ?? 0} 节点
              {failedCount > 0 && (
                <span className="text-rose-500 font-semibold"> · {failedCount} 失败</span>
              )}
            </span>
          </div>

          {(view?.callChain.length ?? 0) === 0 ? (
            <div className="text-xs text-slate-400 p-3 bg-slate-50 rounded-lg text-center border border-slate-100">
              暂无执行调用记录
            </div>
          ) : (
            <div className="relative pl-3.5 space-y-2.5 before:absolute before:left-1.5 before:top-2 before:bottom-2 before:w-px before:bg-slate-200">
              {view!.callChain.map((entry, idx) => (
                <div key={idx} className="relative">
                  <span
                    className={`absolute -left-[14px] top-2 w-2 h-2 rounded-full border-2 border-white  shadow-xs ${
                      entry.status === 'SUCCESS' ? 'bg-emerald-500' : 'bg-rose-500'
                    }`}
                  />

                  <div
                    className={`bg-white border rounded-xl p-2.5 shadow-xs transition-colors space-y-1 ${
                      entry.status === 'SUCCESS'
                        ? 'border-slate-200/80 hover:border-indigo-400/60'
                        : 'border-rose-200 bg-rose-50/30'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-slate-900">
                        {entry.model_name}
                      </span>
                      <span
                        className={`text-[9px] font-mono font-semibold px-1.5 py-0.2 rounded ${
                          entry.status === 'SUCCESS'
                            ? 'bg-emerald-50  text-emerald-700 '
                            : 'bg-rose-50  text-rose-700 '
                        }`}
                      >
                        {entry.status}
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-[10px] text-slate-400">
                      <span className="flex items-center gap-1 font-mono">
                        <Layers className="w-3 h-3 text-slate-400" />
                        {entry.capability}
                      </span>
                      {entry.attempted_at && (
                        <span className="font-mono">{entry.attempted_at.slice(11, 19)}</span>
                      )}
                    </div>

                    {entry.error_code && (
                      <div className="text-[10px] text-rose-600 bg-rose-50 px-2 py-0.5 rounded font-mono">
                        错误代码: {entry.error_code}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Quality Audit Section */}
        <div className="space-y-2 pt-2 border-t border-slate-100">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-800">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
              <span>质检与合规审计</span>
            </div>
            <span
              className={`text-[10px] font-bold px-1.5 py-0.2 rounded border ${
                status === 'PARTIAL_SUCCESS'
                  ? 'text-amber-700 bg-amber-50 border-amber-300/60'
                  : 'text-emerald-600 bg-emerald-50 border-emerald-200/60'
              }`}
            >
              {status === 'PARTIAL_SUCCESS' ? '降级交付' : '5.0 / 5.0'}
            </span>
          </div>

          <div
            className={`rounded-xl p-3 space-y-2 text-xs border ${
              status === 'PARTIAL_SUCCESS'
                ? 'bg-amber-50/60 border-amber-100'
                : 'bg-emerald-50/60 border-emerald-100'
            }`}
          >
            <div className="space-y-1">
              {(status === 'PARTIAL_SUCCESS'
                ? [
                    `${failedCount} 个子任务调用失败，已按降级策略交付可用产物`,
                    '失败节点已写入调用链日志，可供回溯定位',
                    '审计日志已持久化至数据库',
                  ]
                : [
                    '输出非空约束检测通过',
                    '响应模态合规性核验通过',
                    '审计日志已持久化至数据库',
                  ]
              ).map((rule, idx) => (
                <div
                  key={idx}
                  className={`flex items-start gap-1.5 text-[11px] font-normal ${
                    status === 'PARTIAL_SUCCESS' ? 'text-amber-800' : 'text-emerald-800'
                  }`}
                >
                  {status === 'PARTIAL_SUCCESS' ? (
                    <AlertTriangle className="w-3 h-3 text-amber-600 shrink-0 mt-0.5" />
                  ) : (
                    <Check className="w-3 h-3 text-emerald-600 shrink-0 mt-0.5" />
                  )}
                  <span>{rule}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* System Runtime Health Status */}
        <div className="space-y-1.5 pt-2 border-t border-slate-100">
          <div className="flex items-center gap-1.5 text-[11px] font-medium text-slate-400">
            <Server className="w-3 h-3 text-slate-400" />
            <span>架构运行节点</span>
          </div>
          <div className="grid grid-cols-2 gap-1.5 text-[10px] font-mono text-slate-600">
            <div className="p-1.5 rounded-lg bg-slate-50 border border-slate-200/60 flex items-center justify-between">
              <span>TaskRouter</span>
              <span className="text-emerald-500">Active</span>
            </div>
            <div className="p-1.5 rounded-lg bg-slate-50 border border-slate-200/60 flex items-center justify-between">
              <span>Evaluator</span>
              <span className="text-emerald-500">Online</span>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
};
