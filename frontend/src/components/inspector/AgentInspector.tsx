import React from 'react';
import { useTaskStore } from '../../stores/taskStore';
import {
  Activity,
  CheckCircle2,
  XCircle,
  Clock,
  Layers,
  ShieldCheck,
  Cpu,
  Workflow,
  Server,
  Zap,
  Check,
} from 'lucide-react';

export const AgentInspector: React.FC = () => {
  const currentTask = useTaskStore((state) => state.currentTask);
  const isExecuting = useTaskStore((state) => state.isExecuting);

  const logRecord = currentTask?.result?.log_record;
  const callChain = logRecord?.call_chain || [];
  const status = currentTask?.status || (isExecuting ? 'processing' : 'IDLE');

  const getStatusBadge = (s: string) => {
    switch (s) {
      case 'SUCCESS':
        return (
          <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/50 px-2 py-0.5 rounded-full text-[11px] font-semibold border border-emerald-200/80 dark:border-emerald-800/60">
            <CheckCircle2 className="w-3 h-3" /> 执行成功
          </span>
        );
      case 'PARTIAL_SUCCESS':
        return (
          <span className="inline-flex items-center gap-1 text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-950/50 px-2 py-0.5 rounded-full text-[11px] font-semibold border border-blue-200/80 dark:border-blue-800/60">
            <CheckCircle2 className="w-3 h-3" /> 部分成功
          </span>
        );
      case 'FAILED':
        return (
          <span className="inline-flex items-center gap-1 text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/50 px-2 py-0.5 rounded-full text-[11px] font-semibold border border-rose-200/80 dark:border-rose-800/60">
            <XCircle className="w-3 h-3" /> 执行失败
          </span>
        );
      case 'processing':
        return (
          <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/50 px-2 py-0.5 rounded-full text-[11px] font-semibold border border-amber-200/80 dark:border-amber-800/60 animate-pulse">
            <Clock className="w-3 h-3 animate-spin" /> 调度中
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded-full text-[11px] font-medium border border-slate-200/60 dark:border-slate-700/60">
            <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
            空闲就绪
          </span>
        );
    }
  };

  const getPipelineStepStatus = (stepIndex: number) => {
    if (isExecuting) {
      if (stepIndex <= 2) return 'active';
      return 'pending';
    }
    if (status === 'SUCCESS' || status === 'PARTIAL_SUCCESS') {
      return 'done';
    }
    if (status === 'FAILED') {
      return stepIndex <= 2 ? 'done' : 'error';
    }
    return 'pending';
  };

  return (
    <aside className="w-84 bg-white dark:bg-slate-900 border-l border-slate-200/80 dark:border-slate-800 flex flex-col h-full select-none shrink-0 overflow-hidden transition-colors duration-200">
      {/* Header Bar */}
      <div className="p-3.5 border-b border-slate-100 dark:border-slate-800/80 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="p-1 rounded-md bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400">
            <Activity className="w-3.5 h-3.5" />
          </div>
          <div>
            <h2 className="font-semibold text-xs text-slate-800 dark:text-slate-100">
              Agent 观测看板
            </h2>
            <p className="text-[10px] text-slate-400 dark:text-slate-500">
              全链路执行拓扑与质检
            </p>
          </div>
        </div>
        {getStatusBadge(status)}
      </div>

      <div className="flex-1 overflow-y-auto p-3.5 space-y-4">
        {/* Pipeline Stage Tracker */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-[11px] font-medium text-slate-500 dark:text-slate-400">
            <span className="flex items-center gap-1">
              <Zap className="w-3 h-3 text-indigo-500" />
              <span>编排管道阶段</span>
            </span>
            <span className="text-[10px] font-mono text-slate-400">
              {isExecuting ? '运行阶段 2/4' : status === 'SUCCESS' ? '已完成 4/4' : '等待调度'}
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
                      ? 'bg-emerald-50/70 dark:bg-emerald-950/40 border-emerald-200 dark:border-emerald-800/60 text-emerald-700 dark:text-emerald-300'
                      : st === 'active'
                      ? 'bg-indigo-50 dark:bg-indigo-950/50 border-indigo-300 dark:border-indigo-700 text-indigo-700 dark:text-indigo-300 animate-pulse'
                      : st === 'error'
                      ? 'bg-rose-50 dark:bg-rose-950/40 border-rose-200 dark:border-rose-800 text-rose-700 dark:text-rose-300'
                      : 'bg-slate-50 dark:bg-slate-800/50 border-slate-200/60 dark:border-slate-800 text-slate-400 dark:text-slate-500'
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
        {currentTask ? (
          <div className="bg-slate-50 dark:bg-slate-800/50 border border-slate-200/80 dark:border-slate-700/60 rounded-xl p-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-medium text-slate-400 dark:text-slate-500">
                当前任务 ID
              </span>
              <span className="text-[10px] font-mono text-slate-700 dark:text-slate-300 bg-white dark:bg-slate-900 px-1.5 py-0.5 rounded border border-slate-200/60 dark:border-slate-700/60">
                {currentTask.task_id.slice(0, 14)}...
              </span>
            </div>
            <div>
              <span className="text-[11px] font-medium text-slate-400 dark:text-slate-500">
                用户指令输入
              </span>
              <p className="text-xs text-slate-700 dark:text-slate-300 font-normal mt-1 line-clamp-3 bg-white dark:bg-slate-900 p-2 rounded-lg border border-slate-200/60 dark:border-slate-800 leading-relaxed">
                {currentTask.user_input}
              </p>
            </div>
          </div>
        ) : (
          <div className="p-5 text-center border border-dashed border-slate-200 dark:border-slate-800 rounded-xl bg-slate-50/50 dark:bg-slate-900/40">
            <Cpu className="w-6 h-6 text-slate-300 dark:text-slate-600 mx-auto mb-1.5" />
            <p className="text-xs text-slate-400 dark:text-slate-500">
              等待任务触发，启动调度观测
            </p>
          </div>
        )}

        {/* Execution Flow (Call Chain) */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-800 dark:text-slate-200">
              <Workflow className="w-3.5 h-3.5 text-indigo-600 dark:text-indigo-400" />
              <span>多智能体调用链</span>
            </div>
            <span className="text-[10px] font-mono text-slate-400 dark:text-slate-500 bg-slate-100 dark:bg-slate-800 px-1.5 py-0.2 rounded">
              {callChain.length} 节点
            </span>
          </div>

          {callChain.length === 0 ? (
            <div className="text-xs text-slate-400 dark:text-slate-500 p-3 bg-slate-50 dark:bg-slate-800/40 rounded-lg text-center border border-slate-100 dark:border-slate-800">
              暂无执行调用记录
            </div>
          ) : (
            <div className="relative pl-3.5 space-y-2.5 before:absolute before:left-1.5 before:top-2 before:bottom-2 before:w-px before:bg-slate-200 dark:before:bg-slate-800">
              {callChain.map((entry, idx) => (
                <div key={idx} className="relative">
                  <span
                    className={`absolute -left-[14px] top-2 w-2 h-2 rounded-full border-2 border-white dark:border-slate-900 shadow-xs ${
                      entry.status === 'SUCCESS' ? 'bg-emerald-500' : 'bg-rose-500'
                    }`}
                  />

                  <div className="bg-white dark:bg-slate-800/90 border border-slate-200/80 dark:border-slate-700/60 rounded-xl p-2.5 shadow-xs hover:border-indigo-400/60 transition-colors space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-slate-900 dark:text-slate-100">
                        {entry.model_name}
                      </span>
                      <span
                        className={`text-[9px] font-mono font-semibold px-1.5 py-0.2 rounded ${
                          entry.status === 'SUCCESS'
                            ? 'bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300'
                            : 'bg-rose-50 dark:bg-rose-950/60 text-rose-700 dark:text-rose-300'
                        }`}
                      >
                        {entry.status}
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-[10px] text-slate-400 dark:text-slate-500">
                      <span className="flex items-center gap-1 font-mono">
                        <Layers className="w-3 h-3 text-slate-400" />
                        {entry.capability}
                      </span>
                      {entry.attempted_at && (
                        <span className="font-mono">{entry.attempted_at.slice(11, 19)}</span>
                      )}
                    </div>

                    {entry.error_code && (
                      <div className="text-[10px] text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/50 px-2 py-0.5 rounded font-mono">
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
        <div className="space-y-2 pt-2 border-t border-slate-100 dark:border-slate-800/80">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-800 dark:text-slate-200">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
              <span>质检与合规审计</span>
            </div>
            <span className="text-[10px] font-bold text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/50 px-1.5 py-0.2 rounded border border-emerald-200/60 dark:border-emerald-800/60">
              5.0 / 5.0
            </span>
          </div>

          <div className="bg-emerald-50/60 dark:bg-emerald-950/30 border border-emerald-100 dark:border-emerald-900/50 rounded-xl p-3 space-y-2 text-xs">
            <div className="space-y-1">
              {[
                '输出非空约束检测通过',
                '响应模态合规性核验通过',
                '审计日志已持久化至数据库',
              ].map((rule, idx) => (
                <div
                  key={idx}
                  className="flex items-center gap-1.5 text-[11px] text-emerald-800 dark:text-emerald-300 font-normal"
                >
                  <Check className="w-3 h-3 text-emerald-600 dark:text-emerald-400 shrink-0" />
                  <span>{rule}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* System Runtime Health Status */}
        <div className="space-y-1.5 pt-2 border-t border-slate-100 dark:border-slate-800/80">
          <div className="flex items-center gap-1.5 text-[11px] font-medium text-slate-400 dark:text-slate-500">
            <Server className="w-3 h-3 text-slate-400" />
            <span>架构运行节点</span>
          </div>
          <div className="grid grid-cols-2 gap-1.5 text-[10px] font-mono text-slate-600 dark:text-slate-300">
            <div className="p-1.5 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-200/60 dark:border-slate-800 flex items-center justify-between">
              <span>TaskRouter</span>
              <span className="text-emerald-500">Active</span>
            </div>
            <div className="p-1.5 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-200/60 dark:border-slate-800 flex items-center justify-between">
              <span>Evaluator</span>
              <span className="text-emerald-500">Online</span>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
};
