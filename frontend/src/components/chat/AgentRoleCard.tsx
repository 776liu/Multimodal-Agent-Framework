import React, { useState, useMemo } from 'react';
import {
  ChevronRight,
  ChevronDown,
  Bot,
  RefreshCw,
  CheckCircle2,
  AlertTriangle,
  Clock,
} from 'lucide-react';
import type { AgentTraceResponse, ProgressEvent } from '../../types';

/**
 * Agent 角色卡（工单 T-02）
 *
 * 设计取舍（对应工单文档）：
 * 1. 默认折叠为一行摘要 —— 四个角色全展开会淹没对话流；
 * 2. 只渲染后端已记录的事实（agent_messages / progress 事件），不做演示性装饰；
 * 3. 反思重试画成同一张卡内的竖向时间线，呈现为"发现问题 → 修正"的因果链，
 *    而不是两张重复卡片。
 */

/** 角色图标与中文职责说明（对应后端 Agent 实际职责，非虚构） */
const ROLE_META: Record<string, { icon: string; duty: string }> = {
  orchestrator: { icon: '🎯', duty: '拆解意图 · 派发任务 · 聚合结果 · 审查仲裁' },
  writer_agent: { icon: '✍️', duty: '文本生成 · 翻译 · 文案 · 看图写作' },
  image_agent: { icon: '🎨', duty: '文生图 · 图生图' },
  video_agent: { icon: '🎬', duty: '文生视频 · 图生视频' },
  reviewer_agent: { icon: '🔍', duty: '规则快筛 · 质量审查 · 打回建议' },
};

const FALLBACK: { icon: string; duty: string } = { icon: '🤖', duty: '协作 Agent' };

interface AgentRoleCardProps {
  trace: AgentTraceResponse | null;
  events: ProgressEvent[];
  /** 任务总耗时（毫秒） */
  totalElapsedMs?: number;
}

export const AgentRoleCard: React.FC<AgentRoleCardProps> = ({
  trace,
  events,
  totalElapsedMs,
}) => {
  const [expanded, setExpanded] = useState(false);

  /** 把 /agents 轨迹折叠成"每个角色一条时间线" */
  const roleTimelines = useMemo(() => {
    if (!trace?.steps?.length) return [];

    interface Node {
      type: 'dispatch' | 'result';
      step: number;
      status: string | null;
      prompt: string;
      artifactTypes: string[];
      agent: string;
    }

    // 按角色聚合：orchestrator 的 dispatch 与目标 Agent 的 result 配对
    const byRole = new Map<string, Node[]>();
    trace.steps.forEach((s) => {
      s.entries.forEach((e) => {
        // 执行方角色直接读后端写入的 role 字段（T-13）。
        // 此前按 message_type 反推，等于前后端各维护一份推导逻辑，
        // 任一端调整即静默不一致；现由 MessageBus 落库时写明执行方。
        const role =
          e.role || (e.message_type === 'result' ? e.from_agent : e.to_agent);
        const list = byRole.get(role) || [];
        list.push({
          type: e.message_type === 'result' ? 'result' : 'dispatch',
          step: s.step,
          status: e.status ?? null,
          prompt: e.content || '',
          artifactTypes: (e.artifacts || []).map((a) => a.type),
          agent: role,
        });
        byRole.set(role, list);
      });
    });

    return Array.from(byRole.entries()).map(([role, nodes]) => {
      const results = nodes.filter((n) => n.type === 'result');
      // 重试点：同一 (角色, 步骤) 出现多次 result
      const retryKeys = new Set<string>();
      const retried = new Set<string>();
      results.forEach((n) => {
        const key = `${role}:${n.step}`;
        if (retryKeys.has(key)) retried.add(key);
        retryKeys.add(key);
      });
      return {
        role,
        nodes,
        hasRevision: results.some((r) => r.status === 'NEED_REVISION'),
        allOk: results.length > 0 && results.every((r) => r.status === 'SUCCESS'),
        retried,
      };
    });
  }, [trace]);

  /** 审查打回事件（来自 /progress 的 revision 事件），用于因果链说明 */
  const revisionEvents = useMemo(
    () => events.filter((e) => e.stage === 'revision'),
    [events]
  );

  if (!trace || roleTimelines.length === 0) return null;

  const okCount = roleTimelines.filter((r) => r.allOk).length;
  const totalRoles = roleTimelines.length;
  const elapsedSec = totalElapsedMs ? (totalElapsedMs / 1000).toFixed(1) : null;

  return (
    <div className="my-2.5 rounded-xl border border-slate-200/80 bg-slate-50/60 overflow-hidden">
      {/* 折叠态：一行摘要 */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between gap-2 px-3 py-2 text-left hover:bg-slate-100/60 transition-colors"
      >
        <div className="flex items-center gap-1.5 min-w-0">
          {expanded ? (
            <ChevronDown className="w-3.5 h-3.5 text-slate-400 shrink-0" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5 text-slate-400 shrink-0" />
          )}
          <Bot className="w-3.5 h-3.5 text-indigo-500 shrink-0" />
          <span className="text-[11px] font-medium text-slate-700 truncate">
            🎯 Orchestrator · {totalRoles} 个 Agent 协作
          </span>
          {elapsedSec && (
            <span className="text-[10px] font-mono text-slate-400 shrink-0">
              {elapsedSec}s
            </span>
          )}
        </div>
        <span
          className={`text-[10px] font-medium px-1.5 py-0.5 rounded shrink-0 ${
            okCount === totalRoles
              ? 'bg-emerald-50 text-emerald-700'
              : 'bg-amber-50 text-amber-700'
          }`}
        >
          {okCount === totalRoles ? '✓ 全部成功' : `${okCount}/${totalRoles} 成功`}
        </span>
      </button>

      {/* 展开态：角色时间线 */}
      {expanded && (
        <div className="px-3 pb-2.5 space-y-2 border-t border-slate-200/60 pt-2">
          {roleTimelines.map((role) => {
            const meta = ROLE_META[role.role] || FALLBACK;
            return (
              <div key={role.role} className="bg-white rounded-lg border border-slate-200/70 p-2">
                <div className="flex items-center justify-between gap-2 mb-1.5">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className="text-xs">{meta.icon}</span>
                    <span className="text-[11px] font-mono font-semibold text-slate-800 truncate">
                      {role.role}
                    </span>
                  </div>
                  <span
                    className={`text-[9px] font-mono font-semibold px-1.5 py-0.2 rounded shrink-0 ${
                      role.allOk
                        ? 'bg-emerald-50 text-emerald-700'
                        : role.hasRevision
                        ? 'bg-amber-50 text-amber-700'
                        : 'bg-slate-100 text-slate-600'
                    }`}
                  >
                    {role.allOk ? 'OK' : role.hasRevision ? '有修订' : '—'}
                  </span>
                </div>
                <div className="text-[10px] text-slate-400 mb-1.5">{meta.duty}</div>

                {/* 竖向时间线：同一角色的多次执行呈现为因果链 */}
                <div className="space-y-1 pl-3 border-l border-slate-200 ml-0.5">
                  {role.nodes
                    .filter((n) => n.type === 'result')
                    .map((n, i) => {
                      const key = `${role.role}:${n.step}`;
                      const isRetry = role.retried.has(key) && i > 0;
                      const revised =
                        role.retried.has(key) && i > 0 && revisionEvents.length > 0;
                      return (
                        <div key={i} className="relative text-[10px]">
                          <span
                            className={`absolute -left-[13px] top-1 w-1.5 h-1.5 rounded-full ${
                              n.status === 'SUCCESS'
                                ? 'bg-emerald-500'
                                : n.status === 'NEED_REVISION'
                                ? 'bg-amber-500'
                                : 'bg-rose-500'
                            }`}
                          />
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <span className="font-mono text-slate-500">
                              第 {i + 1} 次
                            </span>
                            {n.status === 'SUCCESS' ? (
                              <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                            ) : (
                              <AlertTriangle className="w-3 h-3 text-amber-500" />
                            )}
                            <span className="text-slate-600">
                              {n.artifactTypes.length > 0
                                ? `产出 ${n.artifactTypes.join('/')}`
                                : n.status === 'NEED_REVISION'
                                ? '审查打回'
                                : '完成'}
                            </span>
                            {n.status === 'NEED_REVISION' && (
                              <span className="text-amber-600 font-medium">
                                需修订
                              </span>
                            )}
                          </div>
                          {isRetry && revised && (
                            <div className="text-[9px] text-amber-600/90 mt-0.5 flex items-center gap-1">
                              <RefreshCw className="w-2.5 h-2.5" />
                              <span>审查发现问题后自动重做</span>
                            </div>
                          )}
                          {n.prompt && (
                            <div className="text-[9px] text-slate-400 mt-0.5 truncate max-w-full">
                              {n.prompt}
                            </div>
                          )}
                        </div>
                      );
                    })}
                </div>
              </div>
            );
          })}

          {/* 审查打回的因果说明 */}
          {revisionEvents.length > 0 && (
            <div className="flex items-start gap-1.5 text-[10px] text-amber-700 bg-amber-50 border border-amber-200/70 rounded-lg px-2 py-1.5">
              <Clock className="w-3 h-3 shrink-0 mt-0.5" />
              <span>
                反思闭环：审查不通过时由 Orchestrator 依据审查意见重做该步骤，
                共触发 {revisionEvents.length} 次重试（受重试预算约束，不会无限重做）。
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
