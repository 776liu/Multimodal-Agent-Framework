import React, { useEffect } from 'react';
import { useSessionStore } from '../../stores/sessionStore';
import { useTaskStore } from '../../stores/taskStore';
import {
  MessageSquare,
  Plus,
  Trash2,
  Cpu,
  RefreshCw,
} from 'lucide-react';

export const Sidebar: React.FC = () => {
  const {
    sessions,
    currentSessionId,
    isLoadingSessions,
    loadSessions,
    selectSession,
    createNewSession,
    clearHistory,
  } = useSessionStore();

  const isExecuting = useTaskStore((state) => state.isExecuting);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  return (
    <aside className="w-72 bg-white border-r border-surface-border flex flex-col h-screen select-none shrink-0 shadow-sm">
      {/* Brand Header */}
      <div className="p-4 border-b border-surface-border flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-brand-600 to-brand-400 flex items-center justify-center text-white shadow-md shadow-brand-500/20">
            <Cpu className="w-5 h-5" />
          </div>
          <div>
            <h1 className="font-bold text-sm text-slate-800 tracking-tight leading-tight">
              Agent Studio
            </h1>
            <p className="text-[11px] text-slate-400 font-medium">多模态编排框架</p>
          </div>
        </div>
        <button
          onClick={() => loadSessions()}
          title="刷新会话"
          disabled={isLoadingSessions}
          className="p-1.5 text-slate-400 hover:text-brand-600 hover:bg-slate-50 rounded-lg transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${isLoadingSessions ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* New Session Button */}
      <div className="p-3">
        <button
          onClick={createNewSession}
          disabled={isExecuting}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-brand-50 hover:bg-brand-100 text-brand-700 font-medium text-xs rounded-xl border border-brand-200/60 transition-all duration-150 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
        >
          <Plus className="w-4 h-4 text-brand-600" />
          <span>新建会话</span>
        </button>
      </div>

      {/* Sessions List */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1">
        <div className="text-[11px] font-semibold text-slate-400 px-2 py-1 uppercase tracking-wider">
          历史会话
        </div>

        {sessions.length === 0 && !isLoadingSessions ? (
          <div className="p-4 text-center text-xs text-slate-400">
            暂无会话，请点击上方创建
          </div>
        ) : (
          sessions.map((session) => {
            const isActive = session.session_id === currentSessionId;
            return (
              <button
                key={session.session_id}
                onClick={() => selectSession(session.session_id)}
                disabled={isExecuting}
                className={`w-full group flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-xs font-medium transition-all text-left ${
                  isActive
                    ? 'bg-brand-600 text-white shadow-sm shadow-brand-500/25'
                    : 'text-slate-600 hover:bg-slate-100/80 hover:text-slate-900'
                } disabled:opacity-50`}
              >
                <MessageSquare
                  className={`w-4 h-4 shrink-0 ${
                    isActive ? 'text-white' : 'text-slate-400 group-hover:text-brand-600'
                  }`}
                />
                <span className="truncate flex-1">
                  {session.label || session.session_id}
                </span>
                {isActive && (
                  <span className="w-1.5 h-1.5 rounded-full bg-white shrink-0"></span>
                )}
              </button>
            );
          })
        )}
      </div>

      {/* Footer Info & Actions */}
      <div className="p-3 border-t border-surface-border bg-slate-50/50 flex flex-col gap-2">
        <div className="flex items-center justify-between text-[11px] text-slate-400 px-1">
          <span className="truncate max-w-[150px]">ID: {currentSessionId}</span>
          <span className="inline-flex items-center gap-1 text-emerald-600 font-medium">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
            就绪
          </span>
        </div>
        <button
          onClick={() => {
            if (confirm('确定要清空当前会话的历史记录吗？')) {
              clearHistory();
            }
          }}
          disabled={isExecuting}
          className="w-full flex items-center justify-center gap-1.5 px-3 py-2 text-rose-600 hover:bg-rose-50 rounded-lg text-xs font-medium transition-colors border border-transparent hover:border-rose-200 disabled:opacity-50"
        >
          <Trash2 className="w-3.5 h-3.5" />
          <span>清空当前会话历史</span>
        </button>
      </div>
    </aside>
  );
};
