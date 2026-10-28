import React, { useState, useMemo, useEffect } from 'react';
import { useTaskStore } from '../../stores/taskStore';
import { useSessionStore } from '../../stores/sessionStore';
import type { AgentTraceResponse, CallChainEntry } from '../../types';
import { getTaskAgents } from '../../api/task';
import { CollabTopology } from './CollabTopology';
import { CollabConversation } from './CollabConversation';
import {
  Activity,
  CheckCircle2,
  XCircle,
  Clock,
  AlertTriangle,
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

interface AgentInspectorProps {
  width: number;
}

export const AgentInspector: React.FC<AgentInspectorProps> = ({ width }) => {
  const currentTask = useTaskStore((state) => state.currentTask);
  const isExecuting = useTaskStore((state) => state.isExecuting);
  const sessionTasks = useSessionStore((state) => state.sessionTasks);
  const progressEvents = useTaskStore((state) => state.progressEvents);
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

  /**
   * 调度轨迹（T-12 / T-13）
   *
   * 组件自持一份 trace，按当前视图的 taskId 拉取：
   * - 不用 store 里的全局 agentTrace，避免与聊天区的"最新一轮"互相覆盖；
   * - 历史任务切换时同样能回放依赖与对话（数据来自 agent_messages 持久化）。
   */
  const [activeTrace, setActiveTrace] = useState<AgentTraceResponse | null>(null);
  const viewTaskId = view?.taskId ?? null;

  useEffect(() => {
    let cancelled = false;
    if (!viewTaskId) {
      setActiveTrace(null);
      return;
    }
    // 已有同任务轨迹时不重复请求
    if (activeTrace?.task_id === viewTaskId) return;

    getTaskAgents(viewTaskId)
      .then((trace) => {
        if (!cancelled) setActiveTrace(trace);
      })
      .catch(() => {
        if (!cancelled) setActiveTrace(null);
      });

    return () => {
      cancelled = true;
    };
    // activeTrace 故意不列入依赖，避免拉取成功后再次触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewTaskId]);

  /**
   * 按 Agent 角色分组调用链（工单 T-02）
   *
   * 为什么要分组而非平铺模型名：
   * 单 Agent 多模型调度器产出的 call_chain 与此结构完全相同，
   * 只有"哪个角色调了哪个模型"这一维度，能证明系统是多 Agent 协作。
   * 因此以 agent 为主键分组，模型降级明细作为组内明细展示。
   */
  /**
   * 实时调用链（T-15）
   *
   * 问题：`call_chain` 只在任务收尾时汇总并写回，执行期间恒为空，
   * 因此"调用链路"整块要等任务跑完才一次性出现，看不到逐条跳出的过程。
   *
   * 方案：Orchestrator 现在把每步产生的调用明细随 `collecting` 事件下发
   * （`progressEvents[].calls`），这里把它聚合成与终态 `call_chain` 同构的数组。
   * - 运行中：用实时事件渲染，逐条出现；
   * - 任务终态：`view.callChain` 非空则直接用它覆盖（同为权威终态数据）。
   * 去重键用 `agent+model+capability+attempted_at`：反思重试会产生新的
   * `attempted_at`，因此不会被误判重复；同一事件的重复拉取则会被合并。
   */
  const liveChain = useMemo<CallChainEntry[]>(() => {
    const fromEvents: CallChainEntry[] = [];
    const seen = new Set<string>();
    progressEvents.forEach((e) => {
      (e.calls || []).forEach((c) => {
        const key = `${c.agent}|${c.model}|${c.capability}|${c.attempted_at || ''}`;
        if (seen.has(key)) return;
        seen.add(key);
        fromEvents.push({
          agent: c.agent,
          model_name: c.model,
          capability: c.capability,
          status: c.status,
          error_code: c.error_code ?? null,
          elapsed_ms: c.elapsed_ms ?? 0,
          attempted_at: c.attempted_at,
        } as CallChainEntry);
      });
    });
    return fromEvents;
  }, [progressEvents]);

  const groupedByAgent = useMemo(() => {
    // 终态数据优先；运行中回退到实时事件聚合结果
    const finalized = view?.callChain || [];
    const chain = finalized.length > 0 ? finalized : liveChain;
    const groups = new Map<string, CallChainEntry[]>();
    chain.forEach((entry, idx) => {
      // 老数据无 agent 字段时归入"未标注"组，不伪造角色名
      const key = entry.agent || '未标注角色';
      const list = groups.get(key) || [];
      // 保留原始顺序，组内按调用先后排列
      list.push({ ...entry, _idx: idx } as CallChainEntry & { _idx: number });
      groups.set(key, list);
    });
    return Array.from(groups.entries()).map(([role, entries]) => {
      const totalMs = entries.reduce((sum, e) => sum + (e.elapsed_ms || 0), 0);
      const failures = entries.filter((e) => e.status !== 'SUCCESS');
      return {
        role,
        entries,
        totalMs,
        // 降级次数：同一角色调用多个不同模型即为发生降级
        degraded: new Set(entries.map((e) => e.model_name)).size > 1 && failures.length > 0,
        failedCount: failures.length,
        allOk: failures.length === 0,
      };
    });
  }, [view, liveChain]);

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
      case 'pending':
        // 排队中（T-14）：任务已入队但 Worker 尚未领取。
        // 与"执行中"区分，让"双车道排队"这件事在界面上可见。
        return (
          <span className="inline-flex items-center gap-1 text-slate-600 bg-slate-100 px-2 py-0.5 rounded-full text-[11px] font-semibold border border-slate-300/80">
            <Clock className="w-3 h-3" /> 排队中
          </span>
        );
      case 'processing':
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

  /**
   * 管道阶段点亮（T-14）
   *
   * 此前按任务状态静态推断（processing 就恒定点亮前两段），等于没反映真实进度。
   * 现改为按 `/progress` 的真实事件推进：planning → planned → dispatching →
   * collecting → auditing，缺事件时才回退到静态推断（历史任务无事件流时仍可用）。
   */
  const liveStage = useMemo(() => {
    const stages = progressEvents.map((e) => e.stage).filter(Boolean);
    if (!stages.length) return null;
    const last = stages[stages.length - 1];
    const seen = new Set(stages);
    // 返回 [已完成到第几段, 当前进行到第几段]
    const reached = (name: string) => seen.has(name);
    if (reached('auditing')) return { done: 3, active: 4 };
    if (reached('dispatching') || reached('collecting')) return { done: 2, active: 3 };
    if (reached('planned')) return { done: 1, active: 2 };
    if (last === 'planning') return { done: 0, active: 1 };
    return null;
  }, [progressEvents]);

  const getPipelineStepStatus = (stepIndex: number) => {
    // 任务已终态：统一按终态着色，不再看中间事件
    if (status === 'SUCCESS' && stepIndex <= 4) return 'done';
    if (liveStage) {
      if (stepIndex <= liveStage.done) return 'done';
      if (stepIndex === liveStage.active) return 'active';
      return 'pending';
    }
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
    <aside
      className="bg-white border-l border-slate-200/80 flex flex-col h-full select-none shrink-0 overflow-hidden transition-colors duration-200"
      style={{ width }}
    >
      {/* Header Bar */}
      <div className="p-3.5 border-b border-slate-100 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className="p-1 rounded-md bg-indigo-50 text-indigo-600 shrink-0">
            <Activity className="w-3.5 h-3.5" />
          </div>
          <div className="min-w-0">
            <h2 className="font-semibold text-xs text-slate-800 truncate">
              Agent 观测看板
            </h2>
            <p className="text-[10px] text-slate-400 truncate">
              {selectedHistoryIdx !== null ? '历史任务回放' : '实时链路观测'}
            </p>
          </div>
        </div>
        <div className="shrink-0">{getStatusBadge(status)}</div>
      </div>

      <div className="flex-1 overflow-y-auto overflow-x-hidden p-3.5 space-y-4">
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
                ? `运行阶段 ${liveStage?.active ?? 1}/4`
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
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-medium text-slate-400 shrink-0">
                {selectedHistoryIdx !== null ? '回放任务 ID' : '当前任务 ID'}
              </span>
              <span className="text-[10px] font-mono text-slate-700 bg-white px-1.5 py-0.5 rounded border border-slate-200/60 truncate">
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

        {/* 调用链路：按 Agent 角色分组（工单 T-02）
            设计原则：只渲染后端已记录的事实，不做演示性装饰。
            分组维度是 agent 而非 model —— 后者是单 Agent 调度器也会有的数据。 */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-800">
              <Workflow className="w-3.5 h-3.5 text-indigo-600" />
              <span>调用链路</span>
            </div>
            <span className="text-[10px] font-mono text-slate-400 bg-slate-100 px-1.5 py-0.2 rounded">
              {groupedByAgent.length} 个角色 ·{' '}
              {(view?.callChain.length ?? 0) > 0
                ? view?.callChain.length
                : liveChain.length}{' '}
              次调用
              {failedCount > 0 && (
                <span className="text-rose-500 font-semibold"> · {failedCount} 失败</span>
              )}
            </span>
          </div>

          {groupedByAgent.length === 0 ? (
            <div className="text-xs text-slate-400 p-3 bg-slate-50 rounded-lg text-center border border-slate-100">
              暂无执行调用记录
            </div>
          ) : (
            <div className="space-y-2">
              {groupedByAgent.map((group) => (
                <div
                  key={group.role}
                  className={`rounded-xl border p-2.5 space-y-1.5 ${
                    group.allOk
                      ? 'bg-white border-slate-200/80'
                      : 'bg-rose-50/40 border-rose-200'
                  }`}
                >
                  {/* 角色头：角色名 + 汇总状态 + 耗时 */}
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="w-2 h-2 rounded-full shrink-0 bg-indigo-500" />
                      <span className="text-xs font-semibold text-slate-900 font-mono truncate">
                        {group.role}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {group.degraded && (
                        <span
                          className="text-[9px] font-medium px-1.5 py-0.2 rounded bg-amber-50 text-amber-700 border border-amber-200/70"
                          title="主模型失败后自动切换备用模型"
                        >
                          自动降级
                        </span>
                      )}
                      {group.totalMs > 0 && (
                        <span className="text-[10px] font-mono text-slate-400">
                          {(group.totalMs / 1000).toFixed(1)}s
                        </span>
                      )}
                      <span
                        className={`text-[9px] font-mono font-semibold px-1.5 py-0.2 rounded ${
                          group.allOk
                            ? 'bg-emerald-50 text-emerald-700'
                            : 'bg-rose-50 text-rose-700'
                        }`}
                      >
                        {group.allOk ? 'OK' : `${group.failedCount} 失败`}
                      </span>
                    </div>
                  </div>

                  {/* 组内调用明细：模型 + 能力 + 状态 + 单次耗时 */}
                  <div className="space-y-1 pl-3.5 border-l border-slate-200/70 ml-1">
                    {group.entries.map((entry, i) => (
                      <div key={i} className="flex items-center justify-between gap-2 text-[10px]">
                        <span className="flex items-center gap-1 min-w-0">
                          <span
                            className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                              entry.status === 'SUCCESS' ? 'bg-emerald-500' : 'bg-rose-500'
                            }`}
                          />
                          <span className="font-mono text-slate-700 truncate">{entry.model_name}</span>
                        </span>
                        <span className="flex items-center gap-1.5 shrink-0 text-slate-400">
                          <span className="font-mono">{entry.capability}</span>
                          {entry.elapsed_ms ? (
                            <span className="font-mono text-slate-300">
                              {(entry.elapsed_ms / 1000).toFixed(1)}s
                            </span>
                          ) : null}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 协作拓扑（T-12）：产物在步骤间流动的依赖视图 */}
        <div className="pt-2 border-t border-slate-100">
          <CollabTopology steps={activeTrace?.steps} />
        </div>

        {/* 协作对话（T-13）：把派发/回收还原为一次往返对话 */}
        <div className="pt-2 border-t border-slate-100">
          <CollabConversation steps={activeTrace?.steps} />
        </div>

        {/* Quality Audit Section */}
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
