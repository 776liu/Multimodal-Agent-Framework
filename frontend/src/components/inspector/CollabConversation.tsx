import React, { useMemo } from 'react';
import type { AgentTraceStep } from '../../types';
import {
  CornerDownRight,
  CornerUpLeft,
  MessagesSquare,
  CheckCircle2,
  XCircle,
  AlertTriangle,
} from 'lucide-react';

/**
 * 协作对话流（工单 T-13）
 *
 * 设计意图
 * --------
 * 「调用链路」是**日志形态**（角色 · 耗时 · SUCCESS），而协作的观感来自**对话形态**：
 * 谁向谁派了什么活、谁交回了什么。数据其实早就在 `agent_messages` 里
 * （dispatch / result 两类消息），此前只是被渲染成了表格行。
 *
 * 本组件把它还原成一次往返对话：
 *   Orchestrator → Writer    派发：写一段分镜脚本
 *   Writer → Orchestrator    交付：产出 文本 312 字
 *
 * 执行方角色直接读后端写入的 `role` 字段（T-08 技术债 B），
 * 不再按 `message_type` 反推，避免前后端各维护一份推导逻辑。
 */

interface ConversationItem {
  key: string;
  from: string;
  to: string;
  kind: 'dispatch' | 'result';
  status?: string | null;
  text: string;
  step: number;
  referenceStep: number | null;
}

function summarizeArtifacts(entry: AgentTraceStep['entries'][number]): string {
  const arts = entry.artifacts || [];
  if (!arts.length) return '';
  const counts = new Map<string, number>();
  arts.forEach((a) => counts.set(a.type, (counts.get(a.type) || 0) + 1));
  const label: Record<string, string> = { image: '图片', video: '视频', text: '文本' };
  return Array.from(counts.entries())
    .map(([t, n]) => `${label[t] || t} ×${n}`)
    .join('、');
}

export function buildConversation(steps: AgentTraceStep[] | undefined): ConversationItem[] {
  if (!steps?.length) return [];
  const items: ConversationItem[] = [];
  steps
    .slice()
    .sort((a, b) => a.step - b.step)
    .forEach((s) => {
      s.entries.forEach((e, i) => {
        const isDispatch = e.message_type === 'dispatch';
        // 执行方角色优先读后端写入的 role（T-13）
        const executor =
          e.role || (isDispatch ? e.to_agent : e.from_agent) || 'unknown_agent';

        let text = (e.content || '').trim();
        if (!isDispatch) {
          const summary = summarizeArtifacts(e);
          if (summary) text = summary;           // 回收消息以产物摘要为主
          else if (!text) text = '已完成';
        }
        if (text.length > 84) text = text.slice(0, 84) + '…';

        items.push({
          key: `${s.step}-${i}`,
          from: isDispatch ? e.from_agent : executor,
          to: isDispatch ? executor : e.to_agent,
          kind: isDispatch ? 'dispatch' : 'result',
          status: e.status,
          text,
          step: s.step,
          referenceStep: e.reference_step ?? s.reference_step ?? null,
        });
      });
    });
  return items;
}

const StatusMark: React.FC<{ item: ConversationItem }> = ({ item }) => {
  if (item.kind === 'dispatch') return null;
  if (item.status === 'SUCCESS') {
    return <CheckCircle2 className="w-2.5 h-2.5 text-emerald-500 shrink-0" />;
  }
  if (item.status === 'NEED_REVISION') {
    return <AlertTriangle className="w-2.5 h-2.5 text-amber-500 shrink-0" />;
  }
  return <XCircle className="w-2.5 h-2.5 text-rose-500 shrink-0" />;
};

export const CollabConversation: React.FC<{ steps?: AgentTraceStep[] }> = ({ steps }) => {
  const items = useMemo(() => buildConversation(steps), [steps]);
  const roundTrips = items.filter((i) => i.kind === 'dispatch').length;

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-800">
          <MessagesSquare className="w-3.5 h-3.5 text-indigo-600" />
          <span>协作对话</span>
        </div>
        <span className="text-[10px] font-mono text-slate-400 bg-slate-100 px-1.5 py-0.2 rounded">
          {roundTrips} 次派发 · {items.length} 条消息
        </span>
      </div>

      {items.length === 0 ? (
        <div className="text-xs text-slate-400 p-3 bg-slate-50 rounded-lg text-center border border-slate-100">
          暂无 Agent 间消息记录
        </div>
      ) : (
        <div className="rounded-xl border border-slate-200/80 bg-white p-2 space-y-1">
          {items.map((item) => {
            const isDispatch = item.kind === 'dispatch';
            const Icon = isDispatch ? CornerDownRight : CornerUpLeft;
            return (
              <div
                key={item.key}
                className={`flex items-start gap-1.5 text-[10px] rounded-lg px-1.5 py-1 ${
                  isDispatch ? 'bg-slate-50/70' : 'bg-emerald-50/40'
                }`}
              >
                <Icon
                  className={`w-2.5 h-2.5 mt-0.5 shrink-0 ${
                    isDispatch ? 'text-slate-400' : 'text-emerald-500'
                  }`}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1 flex-wrap">
                    <span className="font-mono font-semibold text-slate-700">
                      {item.from}
                    </span>
                    <span className="text-slate-300">→</span>
                    <span className="font-mono font-semibold text-indigo-600">
                      {item.to}
                    </span>
                    <span
                      className={`text-[9px] px-1 rounded ${
                        isDispatch
                          ? 'bg-slate-100 text-slate-500'
                          : 'bg-emerald-100/70 text-emerald-700'
                      }`}
                    >
                      {isDispatch ? '派发' : '交付'}
                    </span>
                    <StatusMark item={item} />
                  </div>
                  <div className="text-slate-500 truncate" title={item.text}>
                    {item.text || '—'}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
