import React, { useMemo } from 'react';
import type { AgentTraceStep } from '../../types';
import {
  Image as ImageIcon,
  Film,
  FileText,
  ArrowDown,
  CornerLeftUp,
  CheckCircle2,
  XCircle,
  Clock,
} from 'lucide-react';

/**
 * 协作拓扑：产物依赖视图（工单 T-12）
 *
 * 设计意图
 * --------
 * 「调用链路」回答的是"谁调了哪个模型"，但看不出"哪个步骤的产物喂给了哪个步骤"。
 * 本组件按步骤顺序渲染节点，并把 `reference_step` 显式画成依赖边，
 * 让"多 Agent 协作"中最硬的证据——**产物在步骤间流动**——变得可见。
 *
 * 数据来源：`/api/task/{id}/agents` 的 steps[].reference_step 与产物 metadata。
 * 渲染原则：只画后端记录过的真实依赖；无 reference_step 的步骤只画顺序连接，
 * 不臆造依赖关系。
 */

interface StepNode {
  step: number;
  role: string;
  status: string;
  artifacts: Array<{ type: string; url: string }>;
  referenceStep: number | null;
}

const ARTIFACT_META: Record<string, { icon: React.FC<{ className?: string }>; label: string; cls: string }> = {
  image: { icon: ImageIcon, label: '图片', cls: 'text-fuchsia-600 bg-fuchsia-50 border-fuchsia-200/70' },
  video: { icon: Film, label: '视频', cls: 'text-violet-600 bg-violet-50 border-violet-200/70' },
  text: { icon: FileText, label: '文本', cls: 'text-sky-600 bg-sky-50 border-sky-200/70' },
};

function artifactMeta(type: string) {
  return ARTIFACT_META[type] ?? {
    icon: FileText,
    label: type || '产物',
    cls: 'text-slate-600 bg-slate-50 border-slate-200/70',
  };
}

/** 把后端 steps 规整成渲染节点：每个步骤取执行方角色与其产出产物 */
export function buildStepNodes(steps: AgentTraceStep[] | undefined): StepNode[] {
  if (!steps?.length) return [];
  return steps
    .map((s) => {
      // 取 result 类消息作为该步骤的产出与执行方（dispatch 只是派发，不算产出）
      const resultEntry =
        s.entries.find((e) => e.message_type === 'result' && e.status === 'SUCCESS') ||
        s.entries.find((e) => e.message_type === 'result') ||
        s.entries[0];

      // role 优先读后端写入的执行方字段（T-13），回退到语义推导以兼容老数据
      const role =
        resultEntry?.role ||
        (resultEntry?.message_type === 'result'
          ? resultEntry?.from_agent
          : resultEntry?.to_agent) ||
        'unknown_agent';

      // 产出 = 回收产物 − 派发时注入的产物。
      // 末步整体审计会把上游产物原样透传（Reviewer 不生产内容），
      // 若直接展示回收产物，会误标成"审计步骤产出了图+文"。
      const dispatchEntry = s.entries.find((e) => e.message_type === 'dispatch');
      const inputSig = new Set(
        (dispatchEntry?.artifacts || []).map((a) => `${a.type}:${a.url}`)
      );
      const produced = (resultEntry?.artifacts || []).filter(
        (a) => !inputSig.has(`${a.type}:${a.url}`)
      );

      return {
        step: s.step,
        role,
        status: resultEntry?.status || 'UNKNOWN',
        artifacts: produced.map((a) => ({ type: a.type, url: a.url })),
        referenceStep: s.reference_step ?? null,
      };
    })
    .sort((a, b) => a.step - b.step);
}

const StatusDot: React.FC<{ status: string }> = ({ status }) => {
  if (status === 'SUCCESS') {
    return <CheckCircle2 className="w-3 h-3 text-emerald-500 shrink-0" />;
  }
  if (status === 'UNKNOWN' || status === 'DISPATCHED') {
    return <Clock className="w-3 h-3 text-amber-500 shrink-0" />;
  }
  return <XCircle className="w-3 h-3 text-rose-500 shrink-0" />;
};

export const CollabTopology: React.FC<{ steps?: AgentTraceStep[] }> = ({ steps }) => {
  const nodes = useMemo(() => buildStepNodes(steps), [steps]);
  const dependencyCount = nodes.filter((n) => n.referenceStep !== null).length;

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-800">
          <CornerLeftUp className="w-3.5 h-3.5 text-indigo-600" />
          <span>协作拓扑</span>
        </div>
        <span className="text-[10px] font-mono text-slate-400 bg-slate-100 px-1.5 py-0.2 rounded">
          {nodes.length} 个步骤
          {dependencyCount > 0 && (
            <span className="text-indigo-500 font-semibold"> · {dependencyCount} 条依赖</span>
          )}
        </span>
      </div>

      {nodes.length === 0 ? (
        <div className="text-xs text-slate-400 p-3 bg-slate-50 rounded-lg text-center border border-slate-100">
          暂无可还原的步骤轨迹
        </div>
      ) : (
        <div className="rounded-xl border border-slate-200/80 bg-white p-2.5">
          {nodes.map((node, idx) => {
            const isLast = idx === nodes.length - 1;
            const upstream = node.referenceStep !== null
              ? nodes.find((n) => n.step === node.referenceStep)
              : undefined;
            return (
              <div key={node.step}>
                {/* 节点主体 */}
                <div className="flex items-start gap-2">
                  <span className="mt-0.5 w-4 h-4 rounded-full bg-indigo-50 text-indigo-600 text-[9px] font-bold flex items-center justify-center shrink-0 border border-indigo-200/70">
                    {node.step}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <StatusDot status={node.status} />
                      <span className="text-[11px] font-semibold text-slate-800 font-mono truncate">
                        {node.role}
                      </span>
                      {/* 产物类型徽标 */}
                      {node.artifacts.map((a, i) => {
                        const meta = artifactMeta(a.type);
                        const Icon = meta.icon;
                        return (
                          <span
                            key={i}
                            className={`inline-flex items-center gap-0.5 text-[9px] font-medium px-1.5 py-0.2 rounded border ${meta.cls}`}
                          >
                            <Icon className="w-2.5 h-2.5" />
                            {meta.label}
                          </span>
                        );
                      })}
                      {node.artifacts.length === 0 && (
                        <span className="text-[9px] text-slate-400">
                          {node.status === 'DISPATCHED' || node.status === 'UNKNOWN'
                            ? '执行中…'
                            : `无新产物${node.role.includes('review') ? ' · 审计透传' : ''}`}
                        </span>
                      )}
                    </div>

                    {/* 依赖边：显式标注引用了哪个上游步骤的什么产物 */}
                    {node.referenceStep !== null && (
                      <div className="mt-1 flex items-center gap-1 text-[9px] text-indigo-600 bg-indigo-50/70 border border-indigo-100 rounded px-1.5 py-0.5 w-fit">
                        <CornerLeftUp className="w-2.5 h-2.5" />
                        <span>
                          依赖 步骤{node.referenceStep}
                          {upstream && upstream.artifacts.length > 0
                            ? ` 的${upstream.artifacts.map((a) => artifactMeta(a.type).label).join('/')}`
                            : node.referenceStep === 0
                              ? ' 的对话历史产物'
                              : ''}
                        </span>
                      </div>
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
