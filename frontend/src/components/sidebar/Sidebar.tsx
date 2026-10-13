import React, { useEffect, useState, useMemo } from 'react';
import { useSessionStore } from '../../stores/sessionStore';
import { useTaskStore } from '../../stores/taskStore';
import {
  MessageSquare,
  Plus,
  Trash2,
  RefreshCw,
  Search,
  Check,
  Copy,
  Layers,
  ChevronRight,
  Pencil,
  X,
} from 'lucide-react';

interface SidebarProps {
  width: number;
}

export const Sidebar: React.FC<SidebarProps> = ({ width }) => {
  const {
    sessions,
    currentSessionId,
    isLoadingSessions,
    loadSessions,
    selectSession,
    createNewSession,
    renameSession,
    deleteSession,
    clearHistory,
  } = useSessionStore();

  const isExecuting = useTaskStore((state) => state.isExecuting);
  const [searchQuery, setSearchQuery] = useState('');
  const [copiedId, setCopiedId] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  const filteredSessions = useMemo(() => {
    if (!searchQuery.trim()) return sessions;
    const q = searchQuery.toLowerCase();
    return sessions.filter(
      (s) =>
        (s.label && s.label.toLowerCase().includes(q)) ||
        s.session_id.toLowerCase().includes(q)
    );
  }, [sessions, searchQuery]);

  const handleCopyId = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(currentSessionId);
    setCopiedId(true);
    setTimeout(() => setCopiedId(false), 1500);
  };

  const startRename = (e: React.MouseEvent, sessionId: string, currentLabel: string) => {
    e.stopPropagation();
    setRenamingId(sessionId);
    setRenameValue(currentLabel === '新对话' ? '' : currentLabel);
  };

  const commitRename = async () => {
    if (renamingId && renameValue.trim()) {
      await renameSession(renamingId, renameValue);
    }
    setRenamingId(null);
    setRenameValue('');
  };

  return (
    <aside
      className="bg-white border-r border-slate-200/80 flex flex-col h-full select-none shrink-0 transition-colors duration-200 relative"
      style={{ width }}
    >
      {/* Brand Header */}
      <div className="p-4 border-b border-slate-100 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="relative flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 via-indigo-600 to-indigo-800 text-white shadow-md shadow-indigo-500/20">
            <Layers className="w-4 h-4" />
            <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-emerald-400 ring-2 ring-white" />
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <h1 className="font-semibold text-xs tracking-tight text-slate-900">
                Agent Studio
              </h1>
              <span className="text-[10px] px-1.5 py-0.2 rounded font-mono font-medium bg-slate-100 text-slate-600 border border-slate-200">
                v2.0
              </span>
            </div>
            <p className="text-[11px] text-slate-400 font-normal">
              多模态协同编排控制台
            </p>
          </div>
        </div>

        <button
          onClick={() => loadSessions()}
          title="刷新会话列表"
          disabled={isLoadingSessions}
          className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-md transition-all active:scale-95 disabled:opacity-50"
        >
          <RefreshCw
            className={`w-3.5 h-3.5 ${isLoadingSessions ? 'animate-spin text-indigo-500' : ''}`}
          />
        </button>
      </div>

      {/* Action Area: New Session Button */}
      <div className="p-3 space-y-2">
        <button
          onClick={createNewSession}
          disabled={isExecuting}
          className="w-full flex items-center justify-center gap-2 px-3.5 py-2.5 bg-slate-900 hover:bg-slate-800 text-white font-medium text-xs rounded-lg transition-all duration-150 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed shadow-sm shadow-slate-900/10"
        >
          <Plus className="w-3.5 h-3.5 stroke-[2.5]" />
          <span>新建多模态会话</span>
        </button>

        {/* Search Input */}
        <div className="relative flex items-center">
          <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 pointer-events-none" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="搜索会话记录..."
            className="w-full pl-8 pr-2.5 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-md text-slate-700 placeholder-slate-400 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-colors"
          />
        </div>
      </div>

      {/* Sessions List */}
      <div className="flex-1 overflow-y-auto px-2 py-1 space-y-0.5">
        <div className="flex items-center justify-between px-2 py-1 text-[11px] font-medium text-slate-400">
          <span>历史会话</span>
          <span>{filteredSessions.length}</span>
        </div>

        {filteredSessions.length === 0 && !isLoadingSessions ? (
          <div className="py-8 text-center px-4">
            <MessageSquare className="w-6 h-6 text-slate-300 mx-auto mb-2 stroke-[1.5]" />
            <p className="text-xs text-slate-400">
              {searchQuery ? '未找到匹配的会话' : '暂无历史记录，点击上方开启新对话'}
            </p>
          </div>
        ) : (
          filteredSessions.map((session) => {
            const isActive = session.session_id === currentSessionId;
            const isRenaming = renamingId === session.session_id;
            return (
              <div
                key={session.session_id}
                onClick={() => !isRenaming && selectSession(session.session_id)}
                className={`group relative flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium cursor-pointer transition-all ${
                  isActive
                    ? 'bg-indigo-50/80  text-indigo-950  border border-indigo-200/80  shadow-xs'
                    : 'text-slate-600  hover:bg-slate-100/70  hover:text-slate-900  border border-transparent'
                }`}
              >
                <MessageSquare
                  className={`w-3.5 h-3.5 shrink-0 transition-colors ${
                    isActive
                      ? 'text-indigo-600 '
                      : 'text-slate-400 group-hover:text-slate-600 '
                  }`}
                />

                {isRenaming ? (
                  // 重命名输入态
                  <div className="flex-1 flex items-center gap-1">
                    <input
                      autoFocus
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') commitRename();
                        if (e.key === 'Escape') setRenamingId(null);
                      }}
                      onClick={(e) => e.stopPropagation()}
                      placeholder="输入会话名称..."
                      className="flex-1 min-w-0 px-1.5 py-0.5 text-xs border border-indigo-400 rounded focus:outline-none focus:ring-1 focus:ring-indigo-400"
                    />
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        commitRename();
                      }}
                      title="确认"
                      className="p-0.5 text-emerald-600 hover:bg-emerald-50 rounded"
                    >
                      <Check className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setRenamingId(null);
                      }}
                      title="取消"
                      className="p-0.5 text-slate-400 hover:bg-slate-200 rounded"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ) : (
                  <>
                    <span className="truncate flex-1 font-normal tracking-tight">
                      {session.label || session.session_id}
                    </span>

                    {/* hover 操作：重命名 / 删除 */}
                    <div className="hidden group-hover:flex items-center gap-0.5 shrink-0">
                      <button
                        onClick={(e) => startRename(e, session.session_id, session.label)}
                        title="重命名"
                        className="p-1 text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 rounded transition-colors"
                      >
                        <Pencil className="w-3 h-3" />
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          if (confirm(`确定删除会话「${session.label || session.session_id}」吗？\n该操作将级联删除全部消息、任务日志与审计记录，不可恢复。`)) {
                            deleteSession(session.session_id);
                          }
                        }}
                        title="删除会话"
                        className="p-1 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded transition-colors"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>

                    {isActive && !isRenaming && (
                      <ChevronRight className="w-3.5 h-3.5 text-indigo-500 shrink-0 group-hover:hidden" />
                    )}
                  </>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Footer System Status & Operations */}
      <div className="p-3 border-t border-slate-100 bg-slate-50/70 flex flex-col gap-2">
        <div className="flex items-center justify-between text-[11px] px-1 text-slate-500">
          <div className="flex items-center gap-1.5 truncate max-w-[170px]">
            <span className="text-slate-400 font-mono text-[10px]">ID:</span>
            <span className="font-mono text-[11px] truncate text-slate-700">
              {currentSessionId}
            </span>
          </div>
          <button
            onClick={handleCopyId}
            title="复制会话 ID"
            className="p-1 hover:bg-slate-200 rounded transition-colors text-slate-400 hover:text-slate-700"
          >
            {copiedId ? (
              <Check className="w-3 h-3 text-emerald-500" />
            ) : (
              <Copy className="w-3 h-3" />
            )}
          </button>
        </div>

        <div className="flex items-center justify-between px-1 py-0.5 text-[10px] text-slate-400 border-t border-slate-200/50 pt-1.5">
          <span className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            <span>FastAPI + Redis 就绪</span>
          </span>
          <span className="text-slate-400 font-mono">127.0.0.1</span>
        </div>

        <button
          onClick={() => {
            if (confirm('确定要清空当前会话的历史交互记录吗？')) {
              clearHistory();
            }
          }}
          disabled={isExecuting}
          className="w-full flex items-center justify-center gap-1.5 px-2.5 py-1.5 text-rose-600 hover:bg-rose-50 rounded-md text-[11px] font-medium transition-colors border border-transparent hover:border-rose-200/60 disabled:opacity-50"
        >
          <Trash2 className="w-3 h-3" />
          <span>清空当前会话历史</span>
        </button>
      </div>
    </aside>
  );
};
