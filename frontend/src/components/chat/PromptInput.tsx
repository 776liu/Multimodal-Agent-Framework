import React, { useState, useRef, useEffect } from 'react';
import {
  ArrowUp,
  Sparkles,
  Loader2,
  X,
  Palette,
  Compass,
  FileText,
  Layers,
  Zap,
} from 'lucide-react';

interface PromptInputProps {
  onSend: (text: string) => void;
  disabled?: boolean;
}

interface PresetOption {
  label: string;
  category: 'image' | 'plan' | 'summary';
  prompt: string;
}

const PRESET_OPTIONS: PresetOption[] = [
  {
    label: '雨夜霓虹赛博街道',
    category: 'image',
    prompt: '生成一张赛博朋克风格的雨夜霓虹街道图片，电影级光影与反光水洼',
  },
  {
    label: '火星基地与探险记',
    category: 'plan',
    prompt: '生成一张未来火星基地的概念图，并写一段探险日记',
  },
  {
    label: '多模态 Agent 优势评析',
    category: 'summary',
    prompt: '将人工智能多模态 Agent 架构的核心优势写一段 150 字精练评析',
  },
  {
    label: '极简北欧空间渲染',
    category: 'image',
    prompt: '生成一张极简主义北欧阳光客厅设计图，原木与绿植，8K 质感',
  },
  {
    label: '多智能体质检机制',
    category: 'summary',
    prompt: '详细说明多模态 Agent 框架中 Evaluator 质检器的工作原理与校验规则',
  },
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
        200
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

  const getCategoryIcon = (category: string) => {
    switch (category) {
      case 'image':
        return <Palette className="w-3.5 h-3.5 text-indigo-500" />;
      case 'plan':
        return <Compass className="w-3.5 h-3.5 text-emerald-500" />;
      default:
        return <FileText className="w-3.5 h-3.5 text-blue-500" />;
    }
  };

  return (
    <div className="w-full pb-4 px-4 sm:px-6 relative z-20 pointer-events-auto transition-colors duration-200">
      <div className="max-w-4xl mx-auto flex flex-col gap-2">
        {/* Floating Recommendation Chips (悬浮在输入框正上方) */}
        <div className="flex items-center gap-2 overflow-x-auto no-scrollbar py-1 px-1">
          <div className="flex items-center gap-1 text-[11px] font-semibold text-slate-400 shrink-0 select-none">
            <Sparkles className="w-3.5 h-3.5 text-indigo-500" />
            <span>推荐灵感:</span>
          </div>

          {PRESET_OPTIONS.map((item, idx) => (
            <button
              key={idx}
              onClick={() => setText(item.prompt)}
              disabled={disabled}
              className="group flex items-center gap-1.5 text-xs bg-white/90 hover:bg-white text-slate-600 hover:text-indigo-600 px-3 py-1.5 rounded-full shrink-0 border border-slate-200/80 shadow-xs hover:shadow-sm hover:border-indigo-400/60 backdrop-blur-md transition-all active:scale-95 disabled:opacity-40"
            >
              {getCategoryIcon(item.category)}
              <span className="font-medium tracking-tight">{item.label}</span>
            </button>
          ))}
        </div>

        {/* DSH-style Rounded Rectangle Input Card (大圆角长方形输入卡片) */}
        <div className="group/input relative flex flex-col bg-white border border-slate-200/90 rounded-2xl sm:rounded-3xl shadow-md shadow-slate-200/40 focus-within:border-indigo-500/80 focus-within:ring-2 focus-within:ring-indigo-500/15 transition-all overflow-hidden">
          {/* Text Area Input */}
          <div className="px-4 pt-3.5 pb-1 relative">
            <textarea
              ref={textareaRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="向多模态协同 Agent 发送自然语言指令... (Enter 发送, Shift+Enter 换行)"
              disabled={disabled}
              rows={1}
              className="w-full bg-transparent resize-none outline-none text-xs sm:text-sm text-slate-800 placeholder-slate-400 max-h-[200px] disabled:opacity-60 leading-relaxed font-sans"
            />
          </div>

          {/* Bottom Toolbar inside the Rounded Card */}
          <div className="flex items-center justify-between px-3.5 pb-2.5 pt-1 select-none">
            {/* Left Status & Clear */}
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium bg-slate-100/80 text-slate-600 rounded-lg border border-slate-200/50">
                <Layers className="w-3 h-3 text-indigo-500" />
                <span>多模态协同流</span>
              </span>

              {text && !disabled && (
                <button
                  onClick={() => setText('')}
                  title="清空当前输入"
                  className="flex items-center gap-1 text-[11px] text-slate-400 hover:text-slate-600 transition-colors px-1.5 py-0.5 rounded hover:bg-slate-100"
                >
                  <X className="w-3 h-3" />
                  <span>清空</span>
                </button>
              )}
            </div>

            {/* Right Quick Info & Send Action */}
            <div className="flex items-center gap-2.5">
              <span className="text-[11px] font-mono text-slate-400 hidden sm:inline">
                Enter 发送
              </span>

              <button
                onClick={handleSubmit}
                disabled={disabled || !text.trim()}
                className="w-8 h-8 rounded-full flex items-center justify-center bg-indigo-600 hover:bg-indigo-500 active:scale-95 text-white transition-all shadow-xs shadow-indigo-600/30 disabled:opacity-30 disabled:pointer-events-none disabled:bg-slate-300 shrink-0"
                title="发送指令"
              >
                {disabled ? (
                  <Loader2 className="w-4 h-4 animate-spin text-white" />
                ) : (
                  <ArrowUp className="w-4 h-4 stroke-[2.5]" />
                )}
              </button>
            </div>
          </div>
        </div>

        {/* Micro Subtitle note */}
        <div className="flex items-center justify-between text-[11px] text-slate-400 px-2">
          <span className="flex items-center gap-1.5">
            <Zap className="w-3 h-3 text-emerald-500" />
            <span>智能体将自动识别意图、路由模型并执行合规质检</span>
          </span>
          <span className="font-mono text-[10px]">Multimodal Framework</span>
        </div>
      </div>
    </div>
  );
};
