import React, { useState } from 'react';
import type { MessageItem } from '../../types';
import { User, Sparkles, Image as ImageIcon, ExternalLink, X } from 'lucide-react';

interface ChatBubbleProps {
  message: MessageItem;
}

export const ChatBubble: React.FC<ChatBubbleProps> = ({ message }) => {
  const isUser = message.role === 'user';
  const [modalImage, setModalImage] = useState<string | null>(null);

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
      // 纯文本消息
      parsedContent = null;
    }
  }

  return (
    <div className={`flex gap-3.5 my-4 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      {/* Avatar */}
      <div
        className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 shadow-sm ${
          isUser
            ? 'bg-slate-800 text-white'
            : 'bg-gradient-to-tr from-brand-600 to-brand-400 text-white shadow-brand-500/20'
        }`}
      >
        {isUser ? <User className="w-4 h-4" /> : <Sparkles className="w-4 h-4" />}
      </div>

      {/* Bubble Content */}
      <div className={`max-w-[78%] flex flex-col ${isUser ? 'items-end' : 'items-start'}`}>
        <div className="text-[11px] font-medium text-slate-400 mb-1 px-1">
          {isUser ? '你' : 'Agent 协作团队'}
        </div>

        {isUser ? (
          <div className="bg-slate-900 text-white px-4 py-3 rounded-2xl rounded-tr-sm text-sm shadow-sm leading-relaxed whitespace-pre-wrap">
            {message.content}
          </div>
        ) : (
          <div className="bg-white border border-surface-border text-slate-800 p-4 rounded-2xl rounded-tl-sm text-sm shadow-sm space-y-3 w-full">
            {parsedContent?.results ? (
              <div className="space-y-4">
                {parsedContent.results.map((item, idx) => {
                  if (item.type === 'image' && item.url) {
                    return (
                      <div key={idx} className="space-y-2">
                        <div className="flex items-center gap-1.5 text-xs font-semibold text-purple-600 bg-purple-50 px-2.5 py-1 rounded-lg w-fit">
                          <ImageIcon className="w-3.5 h-3.5" />
                          <span>生成的图像工件</span>
                        </div>
                        <div className="relative group rounded-xl overflow-hidden border border-slate-100 bg-slate-50">
                          <img
                            src={item.url}
                            alt="AI Generated"
                            className="w-full max-h-96 object-contain rounded-xl cursor-pointer transition-transform duration-200 group-hover:scale-[1.01]"
                            onClick={() => setModalImage(item.url || null)}
                            loading="lazy"
                          />
                          <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity bg-black/60 text-white text-xs px-2.5 py-1 rounded-md backdrop-blur-sm pointer-events-none flex items-center gap-1">
                            <ExternalLink className="w-3 h-3" />
                            <span>点击全屏查看</span>
                          </div>
                        </div>
                      </div>
                    );
                  }

                  // 文本结果
                  return (
                    <div key={idx} className="space-y-1">
                      {item.type && (
                        <span className="text-[11px] font-semibold text-blue-600 bg-blue-50 px-2 py-0.5 rounded-md inline-block mb-1">
                          {item.type}
                        </span>
                      )}
                      <div className="whitespace-pre-wrap leading-relaxed text-slate-700">
                        {item.content}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : parsedContent?.message ? (
              <div className="text-amber-700 bg-amber-50 p-3 rounded-xl border border-amber-100">
                {parsedContent.message}
              </div>
            ) : (
              <div className="whitespace-pre-wrap leading-relaxed text-slate-700">
                {message.content}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Image Lightbox Modal */}
      {modalImage && (
        <div
          className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in"
          onClick={() => setModalImage(null)}
        >
          <div className="relative max-w-4xl max-h-[90vh]">
            <button
              onClick={() => setModalImage(null)}
              className="absolute -top-10 right-0 text-white/80 hover:text-white p-1 rounded-full bg-white/10 hover:bg-white/20 transition-colors"
            >
              <X className="w-6 h-6" />
            </button>
            <img
              src={modalImage}
              alt="Preview"
              className="max-w-full max-h-[85vh] object-contain rounded-xl shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            />
          </div>
        </div>
      )}
    </div>
  );
};
