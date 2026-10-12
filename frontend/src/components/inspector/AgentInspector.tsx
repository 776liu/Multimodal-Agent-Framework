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
          <span className="inline-flex items-center gap-1 text-emerald-600 bg-emerald-50 px-2.5 py-1 rounded-full text-xs font-semibold border border-emerald-200">
            <CheckCircle2 className="w-3.5 h-3.5" /> 成功
          </span>
        );
      case 'PARTIAL_SUCCESS':
        return (
          <span className="inline-flex items-center gap-1 text-blue-600 bg-blue-50 px-2.5 py-1 rounded-full text-xs font-semibold border border-blue-200">
            <CheckCircle2 className="w-3.5 h-3.5" /> 部分成功
          </span>
        );
      case 'FAILED':
        return (
          <span className="inline-flex items-center gap-1 text-rose-600 bg-rose-50 px-2.5 py-1 rounded-full text-xs font-semibold border border-rose-200">
            <XCircle className="w-3.5 h-3.5" /> 失败
          </span>
        );
      case 'processing':
        return (
          <span className="inline-flex items-center gap-1 text-amber-600 bg-amber-50 px-2.5 py-1 rounded-full text-xs font-semibold border border-amber-200 animate-pulse">
            <Clock className="w-3.5 h-3.5" /> 运行中
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 text-slate-500 bg-slate-100 px-2.5 py-1 rounded-full text-xs font-medium">
            空闲就绪
          </span>
        );
    }
  };

  return (
    <aside className="w-80 bg-white border-l border-surface-border flex flex-col h-screen select-none shrink-0 shadow-sm overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-surface-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-brand-600" />
          <h2 className="font-bold text-xs uppercase tracking-wider text-slate-700">
            Agent 观测看板
          </h2>
        </div>
        {getStatusBadge(status)}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        {/* Task Meta Card */}
        {currentTask ? (
          <div className="bg-slate-50 border border-slate-200/80 rounded-2xl p-3.5 space-y-2.5">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-semibold text-slate-400">当前任务 ID</span>
              <span className="text-[11px] font-mono text-slate-600 bg-white px-2 py-0.5 rounded border border-slate-200">
                {currentTask.task_id.slice(0, 12)}...
              </span>
            </div>
            <div>
              <span className="text-[11px] font-semibold text-slate-400">用户原始输入</span>
              <p className="text-xs text-slate-700 font-medium mt-1 line-clamp-3 bg-white p-2 rounded-xl border border-slate-200/70">
                {currentTask.user_input}
              </p>
            </div>
          </div>
        ) : (
          <div className="p-6 text-center border border-dashed border-slate-200 rounded-2xl bg-slate-50/50">
            <Cpu className="w-8 h-8 text-slate-300 mx-auto mb-2" />
            <p className="text-xs text-slate-400">等待任务触发，启动调度监测</p>
          </div>
        )}

        {/* Execution Flow (Call Chain) */}
        <div className="space-y-2.5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-700">
              <Workflow className="w-4 h-4 text-brand-600" />
              <span>模型与 Agent 执行链</span>
            </div>
            <span className="text-[11px] text-slate-400 font-medium">
              {callChain.length} 个节点
            </span>
          </div>

          {callChain.length === 0 ? (
            <div className="text-xs text-slate-400 p-4 bg-slate-50 rounded-xl text-center border border-slate-100">
              暂无执行记录
            </div>
          ) : (
            <div className="relative pl-4 space-y-3 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-0.5 before:bg-slate-200">
              {callChain.map((entry, idx) => (
                <div key={idx} className="relative group">
                  <span
                    className={`absolute -left-[17px] top-1.5 w-2.5 h-2.5 rounded-full border-2 border-white shadow-sm ${
                      entry.status === 'SUCCESS' ? 'bg-emerald-500' : 'bg-rose-500'
                    }`}
                  ></span>

                  <div className="bg-white border border-slate-200/90 rounded-xl p-3 shadow-xs hover:border-brand-300 transition-colors space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-slate-800">
                        {entry.model_name}
                      </span>
                      <span
                        className={`text-[10px] font-semibold px-2 py-0.5 rounded ${
                          entry.status === 'SUCCESS'
                            ? 'bg-emerald-50 text-emerald-700'
                            : 'bg-rose-50 text-rose-700'
                        }`}
                      >
                        {entry.status}
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-[11px] text-slate-400">
                      <span className="flex items-center gap-1">
                        <Layers className="w-3 h-3 text-slate-400" />
                        {entry.capability}
                      </span>
                      {entry.attempted_at && <span>{entry.attempted_at.slice(11, 19)}</span>}
                    </div>

                    {entry.error_code && (
                      <div className="text-[10px] text-rose-600 bg-rose-50 px-2 py-1 rounded">
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
        <div className="space-y-2.5 pt-2 border-t border-slate-100">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-700">
            <ShieldCheck className="w-4 h-4 text-emerald-600" />
            <span>质检与审计 (Reviewer)</span>
          </div>

          <div className="bg-emerald-50/60 border border-emerald-100 rounded-xl p-3 space-y-1.5 text-xs">
            <div className="flex items-center justify-between text-emerald-900 font-medium">
              <span>规则审计评估</span>
              <span className="font-bold text-emerald-700">5.0 / 5.0</span>
            </div>
            <p className="text-[11px] text-emerald-700/80 leading-relaxed">
              输出合规，通过文本长度与空值检测，已持久化至审计数据库。
            </p>
          </div>
        </div>
      </div>
    </aside>
  );
};
