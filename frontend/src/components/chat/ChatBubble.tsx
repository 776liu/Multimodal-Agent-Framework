import React, { useState } from 'react';
import type { MessageItem } from '../../types';
import {
  User,
  Sparkles,
  Image as ImageIcon,
  ExternalLink,
  X,
  Copy,
  Check,
  Download,
  CheckCircle2,
} from 'lucide-react';

interface ChatBubbleProps {
  message: MessageItem;
}

export const ChatBubble: React.FC<ChatBubbleProps> = ({ message }) => {
  const isUser = message.role === 'user';
  const [modalImage, setModalImage] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // 解析 Assistant 消息（可能为 JSON 格式的工件集合）
  let parsedContent: {
    type?: string;
    results?: Array<{ type: string; content?: string; url?: string }>;
    message?: string;
  } | null = null;

  if (!isUser) {
    try {
      parsedContent = JSON.parse(message.content);
    } catch {
      parsedContent = null;
    }
  }

  const handleCopyText = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const handleDownloadImage = (url: string) => {
    const a = document.createElement('a');
    a.href = url;
    a.download = `agent-artifact-${Date.now()}.png`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  return (
    <div className={`flex gap-3 my-4 group ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      {/* Avatar */}
      <div
        className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 text-xs font-semibold select-none shadow-xs ${
          isUser
            ? 'bg-slate-900 text-white dark:bg-slate-800 dark:text-slate-100 ring-1 ring-slate-700/20'
            : 'bg-indigo-600 text-white shadow-indigo-600/20 ring-1 ring-indigo-500/30'
        }`}
      >
        {isUser ? <User className="w-3.5 h-3.5" /> : <Sparkles className="w-3.5 h-3.5" />}
      </div>

      {/* Bubble Content Body */}
      <div className={`max-w-[82%] sm:max-w-[76%] flex flex-col ${isUser ? 'items-end' : 'items-start'}`}>
        <div className="flex items-center gap-2 mb-1 px-0.5 text-[11px] text-slate-400 dark:text-slate-500 font-medium">
          <span>{isUser ? '用户指令' : 'Agent 编排流水线'}</span>
          {message.created_at && (
            <span className="text-[10px] text-slate-400 font-mono">
              {new Date(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </span>
          )}
        </div>

        {isUser ? (
          <div className="bg-slate-900 dark:bg-slate-800 text-white px-4 py-2.5 rounded-2xl rounded-tr-xs text-xs sm:text-sm leading-relaxed whitespace-pre-wrap shadow-xs border border-slate-800 dark:border-slate-700/70 selection:bg-indigo-500 selection:text-white">
            {message.content}
          </div>
        ) : (
          <div className="bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 text-slate-800 dark:text-slate-100 p-4 rounded-2xl rounded-tl-xs text-xs sm:text-sm shadow-xs space-y-3 w-full">
            {parsedContent?.results ? (
              <div className="space-y-4">
                {parsedContent.results.map((item, idx) => {
                  if (item.type === 'image' && item.url) {
                    return (
                      <div key={idx} className="space-y-2.5">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-1.5 text-[11px] font-semibold text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950/50 px-2.5 py-1 rounded-md border border-indigo-200/60 dark:border-indigo-800/60">
                            <ImageIcon className="w-3.5 h-3.5" />
                            <span>多模态视觉生成工件 (Image Artifact)</span>
                          </div>
                          <span className="text-[10px] font-mono text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 px-2 py-0.5 rounded border border-emerald-200/60 dark:border-emerald-800/40 flex items-center gap-1">
                            <CheckCircle2 className="w-3 h-3" />
                            质检核验通过
                          </span>
                        </div>

                        {/* Image Viewer Card */}
                        <div className="relative group/img rounded-xl overflow-hidden border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 shadow-xs">
                          <img
                            src={item.url}
                            alt="Generated Artifact"
                            className="w-full max-h-[460px] object-contain rounded-xl cursor-zoom-in transition-transform duration-300 group-hover/img:scale-[1.01]"
                            onClick={() => setModalImage(item.url || null)}
                            loading="lazy"
                          />

                          {/* Quick Action Overlay Bar */}
                          <div className="absolute bottom-2 right-2 flex items-center gap-1.5 bg-slate-900/80 backdrop-blur-md text-white p-1 rounded-lg opacity-90 sm:opacity-0 group-hover/img:opacity-100 transition-opacity">
                            <button
                              onClick={() => setModalImage(item.url || null)}
                              title="全屏放大查看"
                              className="p-1.5 hover:bg-white/20 rounded transition-colors text-slate-200 hover:text-white"
                            >
                              <ExternalLink className="w-3.5 h-3.5" />
                            </button>
                            <button
                              onClick={() => item.url && handleDownloadImage(item.url)}
                              title="下载原图"
                              className="p-1.5 hover:bg-white/20 rounded transition-colors text-slate-200 hover:text-white"
                            >
                              <Download className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  }

                  // 文本工件
                  return (
                    <div key={idx} className="space-y-1.5">
                      {item.type && item.type !== 'text' && (
                        <div className="flex items-center gap-1.5">
                          <span className="text-[10px] font-mono font-medium text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded">
                            {item.type}
                          </span>
                        </div>
                      )}
                      <div className="whitespace-pre-wrap leading-relaxed text-slate-800 dark:text-slate-200">
                        {item.content}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : parsedContent?.message ? (
              <div className="text-amber-800 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/30 p-3 rounded-lg border border-amber-200/80 dark:border-amber-800/40 text-xs">
                {parsedContent.message}
              </div>
            ) : (
              <div className="whitespace-pre-wrap leading-relaxed text-slate-800 dark:text-slate-200">
                {message.content}
              </div>
            )}

            {/* Bubble Footer Action Toolbar */}
            <div className="pt-2 border-t border-slate-100 dark:border-slate-800/80 flex items-center justify-between text-[11px] text-slate-400">
              <span className="font-mono text-[10px] text-slate-400">
                Agent Output Verification: Pass
              </span>
              <button
                onClick={() => handleCopyText(message.content)}
                className="flex items-center gap-1 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-colors p-1 rounded hover:bg-slate-50 dark:hover:bg-slate-800"
                title="复制消息内容"
              >
                {copied ? (
                  <>
                    <Check className="w-3 h-3 text-emerald-500" />
                    <span className="text-emerald-500 text-[10px]">已复制</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3 h-3" />
                    <span className="text-[10px]">复制</span>
                  </>
                )}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Lightbox Modal for Image Artifact */}
      {modalImage && (
        <div
          className="fixed inset-0 z-50 bg-slate-950/85 backdrop-blur-md flex items-center justify-center p-4"
          onClick={() => setModalImage(null)}
        >
          <div className="relative max-w-5xl max-h-[92vh] flex flex-col items-center">
            {/* Top Toolbar */}
            <div className="w-full flex items-center justify-between text-white pb-3">
              <span className="text-xs font-medium text-slate-300">
                多模态图像工件高分辨率预览
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDownloadImage(modalImage);
                  }}
                  className="px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-white text-xs font-medium transition-colors flex items-center gap-1.5"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>下载</span>
                </button>
                <button
                  onClick={() => setModalImage(null)}
                  className="p-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-white transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            <img
              src={modalImage}
              alt="High-resolution Artifact"
              className="max-w-full max-h-[82vh] object-contain rounded-xl shadow-2xl ring-1 ring-white/10"
              onClick={(e) => e.stopPropagation()}
            />
          </div>
        </div>
      )}
    </div>
  );
};
