import React, { useRef, useEffect } from 'react';
import { useSessionStore } from '../../stores/sessionStore';
import { useTaskStore } from '../../stores/taskStore';
import { ChatBubble } from './ChatBubble';
import { PromptInput } from './PromptInput';
import {
  PanelRightClose,
  PanelRightOpen,
  Sparkles,
  Loader2,
  Clock,
  Terminal,
} from 'lucide-react';

interface ChatAreaProps {
  inspectorOpen: boolean;
  onToggleInspector: () => void;
}

export const ChatArea: React.FC<ChatAreaProps> = ({
  inspectorOpen,
  onToggleInspector,
}) => {
  const { currentSessionId, messages, isLoadingHistory, addMessage, selectSession } =
    useSessionStore();
  const { isExecuting, activeTaskId, submitTask, error } = useTaskStore();

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isExecuting]);

  const handleSend = async (text: string) => {
    // 立即乐观追加用户消息
    addMessage({
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
    });

    const res = await submitTask(text, currentSessionId);
    if (res?.result?.frontend_response) {
      // 重新拉取完整后端消息同步
      await selectSession(currentSessionId);
    }
  };

  return (
    <main className="flex-1 flex flex-col h-screen bg-[#F8F9FE] overflow-hidden">
      {/* Chat Area Top Bar */}
      <header className="h-16 px-6 border-b border-surface-border bg-white flex items-center justify-between shrink-0 shadow-sm z-10">
        <div className="flex items-center gap-3">
          <div className="flex flex-col">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-sm text-slate-800">
                会话: {currentSessionId}
              </span>
              <span className="px-2 py-0.5 text-[10px] font-medium bg-brand-50 text-brand-700 rounded-full border border-brand-200/50">
                实时状态机
              </span>
            </div>
            <span className="text-[11px] text-slate-400">
              {messages.length} 条交互记录
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {isExecuting && (
            <div className="flex items-center gap-2 bg-amber-50 text-amber-700 border border-amber-200 text-xs px-3 py-1.5 rounded-full animate-pulse">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              <span>任务执行中 (ID: {activeTaskId?.slice(0, 8)}...)</span>
            </div>
          )}

          <button
            onClick={onToggleInspector}
            className={`p-2 rounded-xl border transition-colors flex items-center gap-1.5 text-xs font-medium ${
              inspectorOpen
                ? 'bg-slate-100 text-slate-800 border-slate-300'
                : 'bg-white text-slate-600 hover:bg-slate-50 border-slate-200'
            }`}
            title={inspectorOpen ? '收起 Agent 观测板' : '展开 Agent 观测板'}
          >
            {inspectorOpen ? (
              <PanelRightClose className="w-4 h-4 text-slate-600" />
            ) : (
              <PanelRightOpen className="w-4 h-4 text-brand-600" />
            )}
            <span className="hidden sm:inline">
              {inspectorOpen ? '收起观测板' : '展开观测板'}
            </span>
          </button>
        </div>
      </header>

      {/* Message List */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        <div className="max-w-4xl mx-auto space-y-4">
          {/* Welcome Card if empty */}
          {messages.length === 0 && !isLoadingHistory && (
            <div className="my-12 text-center space-y-4 p-8 border border-dashed border-slate-300 rounded-3xl bg-white/50 max-w-lg mx-auto">
              <div className="w-12 h-12 rounded-2xl bg-brand-100 text-brand-600 flex items-center justify-center mx-auto shadow-inner">
                <Sparkles className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-base font-semibold text-slate-800">
                  多模态 Agent 协同就绪
                </h3>
                <p className="text-xs text-slate-500 mt-1">
                  输入自然语言指令，系统将自动拆解规划、调度专属模型并执行质检
                </p>
              </div>
            </div>
          )}

          {isLoadingHistory ? (
            <div className="flex items-center justify-center py-20 text-slate-400 gap-2 text-xs">
              <Loader2 className="w-4 h-4 animate-spin text-brand-600" />
              <span>加载历史消息中...</span>
            </div>
          ) : (
            messages.map((msg, index) => (
              <ChatBubble key={msg.id ?? index} message={msg} />
            ))
          )}

          {/* Real-time executing placeholder */}
          {isExecuting && (
            <div className="flex gap-3.5 my-4">
              <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-brand-600 to-brand-400 text-white flex items-center justify-center shrink-0 animate-pulse">
                <Loader2 className="w-4 h-4 animate-spin" />
              </div>
              <div className="bg-white border border-surface-border p-4 rounded-2xl rounded-tl-sm text-sm shadow-sm space-y-3 w-full max-w-[78%]">
                <div className="flex items-center gap-2 text-xs font-semibold text-brand-700">
                  <Terminal className="w-3.5 h-3.5" />
                  <span>Agent 编排流水线运转中...</span>
                </div>
                <div className="h-4 bg-slate-100 rounded skeleton-shimmer w-3/4"></div>
                <div className="h-4 bg-slate-100 rounded skeleton-shimmer w-1/2"></div>
              </div>
            </div>
          )}

          {error && (
            <div className="p-3 bg-rose-50 border border-rose-200 text-rose-700 text-xs rounded-xl flex items-center gap-2">
              <Clock className="w-4 h-4 shrink-0" />
              <span>错误: {error}</span>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input */}
      <PromptInput onSend={handleSend} disabled={isExecuting} />
    </main>
  );
};
