import React, { useState, useRef, useEffect } from 'react';
import { Send, Sparkles, Loader2 } from 'lucide-react';

interface PromptInputProps {
  onSend: (text: string) => void;
  disabled?: boolean;
}

const PRESETS = [
  '生成一张赛博朋克风格的雨夜霓虹街道图片',
  '将人工智能多模态 Agent 架构的核心优势写一段 150 字简评',
  '生成一张未来火星基地的概念图，并写一段探险日记',
];

export const PromptInput: React.FC<PromptInputProps> = ({ onSend, disabled }) => {
  const [text, setText] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 自动调整输入框高度
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(
        textareaRef.current.scrollHeight,
        180
      )}px`;
    }
  }, [text]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleSubmit = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  return (
    <div className="w-full bg-white border-t border-surface-border p-4 shadow-sm">
      {/* Preset Quick Chips */}
      <div className="max-w-4xl mx-auto mb-3 flex items-center gap-2 overflow-x-auto pb-1 scrollbar-none">
        <span className="text-[11px] font-semibold text-slate-400 shrink-0 flex items-center gap-1">
          <Sparkles className="w-3 h-3 text-brand-500" />
          快捷提示词:
        </span>
        {PRESETS.map((preset, idx) => (
          <button
            key={idx}
            onClick={() => setText(preset)}
            disabled={disabled}
            className="text-xs bg-slate-100 hover:bg-brand-50 text-slate-600 hover:text-brand-700 px-3 py-1.5 rounded-full shrink-0 border border-slate-200/60 transition-colors disabled:opacity-50"
          >
            {preset}
          </button>
        ))}
      </div>

      {/* Input Form */}
      <div className="max-w-4xl mx-auto relative flex items-end gap-2 bg-slate-50 border border-slate-200/80 rounded-2xl p-2 focus-within:ring-2 focus-within:ring-brand-500/20 focus-within:border-brand-500 transition-all shadow-inner">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="向 Agent 发送指令... (Enter 发送, Shift+Enter 换行)"
          disabled={disabled}
          rows={1}
          className="w-full bg-transparent resize-none outline-none text-sm text-slate-800 placeholder-slate-400 px-2 py-1 max-h-[180px] disabled:opacity-60"
        />

        <button
          onClick={handleSubmit}
          disabled={disabled || !text.trim()}
          className="p-2.5 rounded-xl bg-brand-600 hover:bg-brand-700 active:scale-95 text-white transition-all shadow-md shadow-brand-500/20 disabled:opacity-40 disabled:pointer-events-none shrink-0"
        >
          {disabled ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Send className="w-4 h-4" />
          )}
        </button>
      </div>

      <div className="max-w-4xl mx-auto mt-2 flex items-center justify-between text-[11px] text-slate-400 px-1">
        <span>支持纯文本交互、图像生成以及链式多模态任务拆解</span>
        <span>按 Enter 发送</span>
      </div>
    </div>
  );
};
