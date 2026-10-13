import React, { useRef, useEffect } from 'react';
import { useSessionStore } from '../../stores/sessionStore';
import { useTaskStore } from '../../stores/taskStore';
import { ChatBubble } from './ChatBubble';
import { PromptInput } from './PromptInput';
import {
  PanelRightClose,
  PanelRightOpen,
  Loader2,
  Clock,
  Terminal,
  Zap,
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
    // 乐观追加用户消息
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
    <main className="flex-1 flex flex-col h-full bg-slate-50 dark:bg-slate-950 overflow-hidden relative transition-colors duration-200">
      {/* Workspace Top Header Bar */}
      <header className="h-14 px-5 border-b border-slate-200/80 dark:border-slate-800 bg-white/90 dark:bg-slate-900/90 backdrop-blur-md flex items-center justify-between shrink-0 z-10 transition-colors">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-xs text-slate-800 dark:text-slate-100 tracking-tight">
              工作区:
            </span>
            <span className="font-mono text-xs text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded border border-slate-200/60 dark:border-slate-700/60">
              {currentSessionId}
            </span>
            <span className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium bg-indigo-50 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-300 rounded-full border border-indigo-200/60 dark:border-indigo-800/60">
              <Zap className="w-3 h-3 text-indigo-500" />
              <span>协同调度流水线</span>
            </span>
          </div>
          <span className="text-[11px] text-slate-400 dark:text-slate-500 hidden md:inline">
            ({messages.length} 条记录)
          </span>
        </div>

        {/* Header Right Tools */}
        <div className="flex items-center gap-2">
          {isExecuting && (
            <div className="flex items-center gap-1.5 bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800/60 text-[11px] px-2.5 py-1 rounded-full animate-pulse">
              <Loader2 className="w-3 h-3 animate-spin text-amber-600 dark:text-amber-400" />
              <span>流水线运行中</span>
            </div>
          )}

          {/* Inspector Toggle Button */}
          <button
            onClick={onToggleInspector}
            className={`p-1.5 sm:px-2.5 sm:py-1.5 rounded-lg border transition-all flex items-center gap-1.5 text-xs font-medium active:scale-95 ${
              inspectorOpen
                ? 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-slate-100 border-slate-300 dark:border-slate-700'
                : 'bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/70 border-slate-200 dark:border-slate-800'
            }`}
            title={inspectorOpen ? '收起 Agent 观测看板' : '展开 Agent 观测看板'}
          >
            {inspectorOpen ? (
              <PanelRightClose className="w-4 h-4 text-slate-600 dark:text-slate-300" />
            ) : (
              <PanelRightOpen className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
            )}
            <span className="hidden sm:inline">
              {inspectorOpen ? '收起看板' : '展开观测看板'}
            </span>
          </button>
        </div>
      </header>

      {/* Message & Interaction Stream */}
      <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-4 bg-grid-pattern">
        <div className="max-w-4xl mx-auto space-y-4">
          {/* Welcome Hint When Messages Empty (仅一行说明文字) */}
          {messages.length === 0 && !isLoadingHistory && (
            <div className="mt-16 sm:mt-24 text-center select-none">
              <p className="text-xs text-slate-400 dark:text-slate-500 leading-relaxed">
                输入自然语言指令，系统将自动拆解规划、调度专属模型并执行质检
              </p>
            </div>
          )}

          {isLoadingHistory ? (
            <div className="flex items-center justify-center py-24 text-slate-400 gap-2 text-xs">
              <Loader2 className="w-4 h-4 animate-spin text-indigo-600" />
              <span>载入会话记录中...</span>
            </div>
          ) : (
            messages.map((msg, index) => (
              <ChatBubble key={msg.id ?? index} message={msg} />
            ))
          )}

          {/* Real-time executing animation indicator */}
          {isExecuting && (
            <div className="flex gap-3 my-4">
              <div className="w-7 h-7 rounded-lg bg-indigo-600 text-white flex items-center justify-center shrink-0 animate-pulse shadow-sm">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              </div>
              <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 p-4 rounded-2xl rounded-tl-xs text-xs sm:text-sm shadow-xs space-y-3 w-full max-w-[80%]">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-xs font-semibold text-indigo-600 dark:text-indigo-400">
                    <Terminal className="w-3.5 h-3.5" />
                    <span>多模态编排流水线正在执行...</span>
                  </div>
                  <span className="text-[10px] font-mono text-slate-400">
                    Task ID: {activeTaskId?.slice(0, 8)}
                  </span>
                </div>

                {/* Progress Pipeline Dots */}
                <div className="grid grid-cols-3 gap-2 py-1">
                  <div className="h-1.5 rounded-full bg-indigo-500 animate-pulse" />
                  <div className="h-1.5 rounded-full bg-indigo-300 dark:bg-indigo-900 animate-pulse delay-150" />
                  <div className="h-1.5 rounded-full bg-slate-200 dark:bg-slate-800" />
                </div>

                <div className="space-y-2 pt-1">
                  <div className="h-3.5 bg-slate-100 dark:bg-slate-800 rounded skeleton-shimmer w-3/4" />
                  <div className="h-3.5 bg-slate-100 dark:bg-slate-800 rounded skeleton-shimmer w-1/2" />
                </div>
              </div>
            </div>
          )}

          {error && (
            <div className="p-3 bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-rose-700 dark:text-rose-300 text-xs rounded-xl flex items-center gap-2">
              <Clock className="w-4 h-4 shrink-0" />
              <span>执行异常: {error}</span>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input Form Dock */}
      <PromptInput onSend={handleSend} disabled={isExecuting} />
    </main>
  );
};
