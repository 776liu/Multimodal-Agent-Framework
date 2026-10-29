import React, { useMemo, useState } from 'react';
import type { AgentTraceStep, CallChainEntry } from '../../types';
import {
  Image as ImageIcon,
  Film,
  FileText,
  ArrowDown,
  CornerUpLeft,
  CheckCircle2,
  XCircle,
  Clock,
  ChevronDown,
  ChevronRight,
  Target,
  Sparkles,
  RefreshCw,
  ScrollText,
} from 'lucide-react';

/**
 * 协作链路（合并视图）
 *
 * 为什么合并
 * ---------
 * 原先前端把同一批事件拆成三块分别渲染：
 *   - 「调用链路」：按角色分组，展示模型/能力/耗时
 *   - 「协作拓扑」：按步骤展示节点与产物依赖
 *   - 「协作对话」：派发/回收的消息往返
 * 三者是同一件事的三种切面，导致右栏要滚三遍才能读完一次任务。
 *
 * 合并后的信息模型（单棵层级树）：
 *   步骤(step) → 执行角色(agent) → 模型调用(call) → 产物(artifact)
 * 「派发/交付」属于传输层细节，压缩为节点内的两行文字；
 * 原始消息流保留为节点可展开的「原始消息」，作为可追溯证据——
 * 可视化被质疑时能点开看到未经加工的 agent_messages 记录。
 *
 * 数据来源
 * --------
 * - steps：`/api/task/{id}/agents`（agent_messages，实时写入）
 * - callChain：终态取 log_record.call_chain；运行中取 progressEvents[].calls 聚合
 * 两者都带 `step` 字段（T-16），因此可按步骤精确归并——
 * 这一步之前做不到，因为 CallChainEntry 没有步骤号，
 * 而 reviewer_agent 会在多个步骤各出现一次，仅按角色名合并会串。
 */

interface CollabNode {
  step: number;
  role: string;
  /** 步骤阶段：planning（编排器拆解）/ produce（业务产��）/ audit（整体审计） */
  kind: 'planning' | 'produce' | 'audit';
  status: string;
  calls: CallChainEntry[];
  /** 本步自己新产出的产物（已剔除审计透传的上游产物） */
  produced: Array<{ type: string; url: string }>;
  inputArtifacts: Array<{ type: string; url: string }>;
  referenceStep: number | null;
  /** 派发指令摘要（来自 dispatch 消息） */
  dispatchText: string;
  /** 原始消息（供展开追溯） */
  rawEntries: AgentTraceStep['entries'];
}

const ROLE_META: Record<string, { icon: React.FC<{ className?: string }>; label: string }> = {
  orchestrator: { icon: Target, label: '编排器' },
  writer_agent: { icon: FileText, label: 'Writer' },
  image_agent: { icon: ImageIcon, label: 'Image' },
  video_agent: { icon: Film, label: 'Video' },
  reviewer_agent: { icon: Sparkles, label: 'Reviewer' },
};

const ARTIFACT_META: Record<string, { icon: React.FC<{ className?: string }>; label: string; cls: string }> = {
  image: { icon: ImageIcon, label: '图片', cls: 'text-fuchsia-600 bg-fuchsia-50 border-fuchsia-200/70' },
  video: { icon: Film, label: '视频', cls: 'text-violet-600 bg-violet-50 border-violet-200/70' },
  text: { icon: FileText, label: '文本', cls: 'text-sky-600 bg-sky-50 border-sky-200/70' },
};

function artifactMeta(type: string) {
  return ARTIFACT_META[type] ?? {
    icon: FileText, label: type || '产物',
    cls: 'text-slate-600 bg-slate-50 border-slate-200/70',
  };
}

function roleIcon(role: string) {
  return (ROLE_META[role]?.icon) ?? Sparkles;
}

/** 把 steps 与 callChain 按步骤号归并为节点列表 */
export function buildCollabNodes(
  steps: AgentTraceStep[] | undefined,
  callChain: CallChainEntry[] | undefined
): CollabNode[] {
  const callsByStep = new Map<number, CallChainEntry[]>();
  (callChain || []).forEach((c) => {
    const s = c.step ?? 0;
    const list = callsByStep.get(s) || [];
    list.push(c);
    callsByStep.set(s, list);
  });

  const stepMap = new Map<number, AgentTraceStep>();
  (steps || []).forEach((s) => stepMap.set(s.step, s));

  // 步骤号并集：既包含 agent_messages 里的业务步骤，也包含仅存在于调用链的
  // 步骤 0（编排器拆解——它不经过 MessageBus，因此没有 agent_messages 记录）
  const allSteps = Array.from(new Set<number>([
    ...Array.from(stepMap.keys()),
    ...Array.from(callsByStep.keys()),
  ])).sort((a, b) => a - b);

  const maxStep = allSteps.length ? Math.max(...allSteps) : 0;

  return allSteps.map((step) => {
    const s = stepMap.get(step);
    const calls = callsByStep.get(step) || [];
    const entries = s?.entries || [];

    const resultEntry =
      entries.find((e) => e.message_type === 'result' && e.status === 'SUCCESS') ||
      entries.find((e) => e.message_type === 'result') ||
      entries[0];
    const dispatchEntry = entries.find((e) => e.message_type === 'dispatch');

    const role =
      (calls[0]?.agent) ||
      resultEntry?.role ||
      (resultEntry?.message_type === 'result'
        ? resultEntry?.from_agent
        : resultEntry?.to_agent) ||
      'orchestrator';

    // 产出 = 回收产物 − 派发时注入的产物（末步整体审计会原样透传，不能算产出）
    const inputSig = new Set(
      (dispatchEntry?.artifacts || []).map((a) => `${a.type}:${a.url}`)
    );
    const inputArtifacts = (dispatchEntry?.artifacts || []).map((a) => ({
      type: a.type, url: a.url,
    }));
    const produced = (resultEntry?.artifacts || [])
      .filter((a) => !inputSig.has(`${a.type}:${a.url}`))
      .map((a) => ({ type: a.type, url: a.url }));

    let kind: CollabNode['kind'] = 'produce';
    if (step === 0) kind = 'planning';
    else if (maxStep > 0 && step === maxStep &&
             entries.length > 0 &&
             entries.every((e) => (e.role || e.from_agent) === 'reviewer_agent') &&
             produced.length === 0) {
      kind = 'audit';
    }

    return {
      step,
      role,
      kind,
      status: resultEntry?.status || calls[0]?.status || 'DISPATCHED',
      calls,
      produced,
      inputArtifacts,
      referenceStep: s?.reference_step ?? null,
      dispatchText: (dispatchEntry?.content || '').trim(),
      rawEntries: entries,
    };
  });
}

const StatusIcon: React.FC<{ status: string }> = ({ status }) => {
  if (status === 'SUCCESS') return <CheckCircle2 className="w-3 h-3 text-emerald-500 shrink-0" />;
  if (status === 'DISPATCHED' || status === 'UNKNOWN' || status === 'processing') {
    return <Clock className="w-3 h-3 text-indigo-500 shrink-0 animate-pulse" />;
  }
  if (status === 'NEED_REVISION') return <RefreshCw className="w-3 h-3 text-amber-500 shrink-0" />;
  return <XCircle className="w-3 h-3 text-rose-500 shrink-0" />;
};

const fmtMs = (ms?: number) => (ms && ms > 0 ? `${(ms / 1000).toFixed(1)}s` : '—');

interface CollabViewProps {
  steps?: AgentTraceStep[];
  callChain?: CallChainEntry[];
}

export const CollabView: React.FC<CollabViewProps> = ({ steps, callChain }) => {
  const nodes = useMemo(() => buildCollabNodes(steps, callChain), [steps, callChain]);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const totalCalls = nodes.reduce((n, x) => n + x.calls.length, 0);
  const totalMs = nodes.reduce(
    (n, x) => n + x.calls.reduce((m, c) => m + (c.elapsed_ms || 0), 0), 0
  );
  const failCount = nodes.reduce(
    (n, x) => n + x.calls.filter((c) => c.status !== 'SUCCESS').length, 0
  );
  const depCount = nodes.filter((x) => x.referenceStep !== null && x.step !== 0).length;

  const toggle = (step: number) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(step) ? next.delete(step) : next.add(step);
      return next;
    });

  return (
    <div className="space-y-1.5">
      {/* 标题 + 汇总 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-800">
          <CornerUpLeft className="w-3.5 h-3.5 text-indigo-600" />
          <span>协作链路</span>
        </div>
        <span className="text-[10px] font-mono text-slate-400 bg-slate-100 px-1.5 py-0.2 rounded">
          {nodes.length} 步 · {totalCalls} 次调用 · {fmtMs(totalMs)}
          {failCount > 0 && <span className="text-rose-500 font-semibold"> · {failCount} 失败</span>}
          {depCount > 0 && <span className="text-indigo-500 font-semibold"> · {depCount} 依赖</span>}
        </span>
      </div>

      {nodes.length === 0 ? (
        <div className="text-xs text-slate-400 p-3 bg-slate-50 rounded-lg text-center border border-slate-100">
          暂无可还原的执行轨迹
        </div>
      ) : (
        <div className="rounded-xl border border-slate-200/80 bg-white p-2.5">
          {nodes.map((node, idx) => {
            const isLast = idx === nodes.length - 1;
            const Icon = roleIcon(node.role);
            const isOpen = expanded.has(node.step);
            const stepMs = node.calls.reduce((m, c) => m + (c.elapsed_ms || 0), 0);
            const multiCall = node.calls.length > 1;

            return (
              <div key={node.step}>
                {/* ---- 节点主体 ---- */}
                <div className="flex items-start gap-2">
                  <span
                    className={`mt-0.5 w-4 h-4 rounded-full text-[9px] font-bold flex items-center justify-center shrink-0 border ${
                      node.kind === 'planning'
                        ? 'bg-indigo-100 text-indigo-700 border-indigo-300/70'
                        : 'bg-slate-50 text-slate-600 border-slate-200'
                    }`}
                  >
                    {node.step === 0 ? '⓪' : node.step}
                  </span>

                  <div className="min-w-0 flex-1">
                    {/* 角色 + 状态 + 耗时 */}
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <StatusIcon status={node.status} />
                      <Icon className="w-3 h-3 text-slate-500 shrink-0" />
                      <span className="text-[11px] font-semibold text-slate-800 font-mono truncate">
                        {node.role}
                      </span>
                      {node.kind === 'planning' && (
                        <span className="text-[9px] px-1 rounded bg-indigo-50 text-indigo-600 border border-indigo-200/60">
                          意图拆解
                        </span>
                      )}
                      {node.kind === 'audit' && (
                        <span className="text-[9px] px-1 rounded bg-slate-100 text-slate-500">
                          整体审计
                        </span>
                      )}
                      {multiCall && (
                        <span className="text-[9px] px-1 rounded bg-amber-50 text-amber-700 border border-amber-200/60">
                          {node.calls.length} 次调用
                        </span>
                      )}
                      <span className="ml-auto text-[10px] font-mono text-slate-400 shrink-0">
                        {fmtMs(stepMs)}
                      </span>
                    </div>

                    {/* 派发指令（压缩自「协作对话」的 dispatch） */}
                    {node.dispatchText && (
                      <div
                        className="mt-0.5 text-[10px] text-slate-500 truncate"
                        title={node.dispatchText}
                      >
                        <span className="text-slate-400">派发：</span>
                        {node.kind === 'planning'
                          ? `拆解为 ${nodes.filter((n) => n.step > 0 && n.kind !== 'audit').length} 个子任务`
                          : node.dispatchText}
                      </div>
                    )}

                    {/* 模型调用明细（原「调用链路」内联） */}
                    {node.calls.length > 0 && (
                      <div className="mt-1 pl-1.5 border-l border-slate-200/80 space-y-0.5">
                        {node.calls.map((c, i) => (
                          <div
                            key={i}
                            className="flex items-center gap-1 text-[10px] min-w-0"
                          >
                            <span
                              className={`w-1 h-1 rounded-full shrink-0 ${
                                c.status === 'SUCCESS' ? 'bg-emerald-500' : 'bg-rose-500'
                              }`}
                            />
                            <span className="font-mono text-slate-600 truncate">
                              {c.model_name}
                            </span>
                            <span className="text-slate-300">·</span>
                            <span className="text-slate-400 shrink-0">{c.capability}</span>
                            {c.error_code ? (
                              <span className="text-[9px] text-rose-600 shrink-0">
                                ({c.error_code})
                              </span>
                            ) : null}
                            {i > 0 && (
                              <span className="text-[9px] px-1 rounded bg-amber-50 text-amber-700 shrink-0">
                                降级
                              </span>
                            )}
                            <span className="ml-auto font-mono text-slate-400 shrink-0">
                              {fmtMs(c.elapsed_ms)}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* 产物 */}
                    <div className="mt-1 flex items-center gap-1 flex-wrap">
                      {node.produced.map((a, i) => {
                        const meta = artifactMeta(a.type);
                        const AIcon = meta.icon;
                        return (
                          <span
                            key={`p${i}`}
                            className={`inline-flex items-center gap-0.5 text-[9px] font-medium px-1.5 py-0.2 rounded border ${meta.cls}`}
                          >
                            <AIcon className="w-2.5 h-2.5" />
                            {meta.label}
                          </span>
                        );
                      })}
                      {node.produced.length === 0 && (
                        <span className="text-[9px] text-slate-400">
                          {node.status === 'DISPATCHED' || node.status === 'UNKNOWN'
                            ? '执行中…'
                            : '无新产物'}
                        </span>
                      )}
                      {node.inputArtifacts.length > 0 && node.kind !== 'planning' && (
                        <span className="text-[9px] text-slate-400">
                          输入 {node.inputArtifacts.map((a) => artifactMeta(a.type).label).join('/')}
                        </span>
                      )}
                    </div>

                    {/* 依赖标记 */}
                    {node.referenceStep !== null && node.step !== 0 && (
                      <div className="mt-1 flex items-center gap-1 text-[9px] text-indigo-600 bg-indigo-50/70 border border-indigo-100 rounded px-1.5 py-0.5 w-fit">
                        <CornerUpLeft className="w-2.5 h-2.5" />
                        <span>
                          依赖 步骤{node.referenceStep}
                          {node.referenceStep === 0
                            ? ' 的对话历史产物'
                            : ` 的${(nodes.find((n) => n.step === node.referenceStep)?.produced || [])
                                .map((a) => artifactMeta(a.type).label)
                                .join('/') || '产物'}`}
                        </span>
                      </div>
                    )}

                    {/* 原始消息（可展开追溯，作为可视化未造假的证据） */}
                    {node.rawEntries.length > 0 && (
                      <>
                        <button
                          onClick={() => toggle(node.step)}
                          className="mt-1 flex items-center gap-0.5 text-[9px] text-slate-400 hover:text-slate-600 transition-colors"
                        >
                          {isOpen ? (
                            <ChevronDown className="w-2.5 h-2.5" />
                          ) : (
                            <ChevronRight className="w-2.5 h-2.5" />
                          )}
                          <ScrollText className="w-2.5 h-2.5" />
                          原始消息 ({node.rawEntries.length})
                        </button>
                        {isOpen && (
                          <div className="mt-1 space-y-0.5 rounded-lg bg-slate-50/80 border border-slate-200/60 p-1.5">
                            {node.rawEntries.map((e, i) => (
                              <div key={i} className="text-[9px] font-mono text-slate-500 truncate">
                                <span className="text-slate-400">[{e.message_type}]</span>{' '}
                                {e.from_agent} → {e.to_agent}
                                {e.status ? ` · ${e.status}` : ''}
                              </div>
                            ))}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </div>

                {/* 顺序连接线 */}
                {!isLast && (
                  <div className="flex items-center gap-1 pl-[7px] py-0.5">
                    <ArrowDown className="w-3 h-3 text-slate-300" />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
