import React, { useRef, useState } from 'react';

interface PanelResizerProps {
  /**
   * 拖拽条所在的一侧：
   * - 'right'：面板位于左侧，拖拽条贴在它的右缘（向右拖动使面板变宽）
   * - 'left'：面板位于右侧，拖拽条贴在它的左缘（向左拖动使面板变宽）
   */
  edge: 'right' | 'left';
  /** 当前面板宽度（px） */
  width: number;
  min: number;
  max: number;
  /** 双击复位到的默认宽度 */
  defaultWidth: number;
  onWidthChange: (width: number) => void;
  /** 拖拽结束时回调（用于持久化） */
  onWidthCommit?: (width: number) => void;
  label: string;
}

const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, Math.round(value)));

export const PanelResizer: React.FC<PanelResizerProps> = ({
  edge,
  width,
  min,
  max,
  defaultWidth,
  onWidthChange,
  onWidthCommit,
  label,
}) => {
  const [dragging, setDragging] = useState(false);
  const startRef = useRef({ x: 0, width });
  const latestWidthRef = useRef(width);
  const lastDownAtRef = useRef(0);

  const applyWidth = (next: number) => {
    latestWidthRef.current = next;
    onWidthChange(next);
  };

  const resetToDefault = () => {
    applyWidth(defaultWidth);
    onWidthCommit?.(defaultWidth);
  };

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;

    // 双击（300ms 内两次按下）= 恢复默认宽度；用指针事件自行判定，
    // 避免 preventDefault 抑制 click/dblclick 兼容事件导致的失效
    const now = Date.now();
    if (now - lastDownAtRef.current < 300) {
      lastDownAtRef.current = 0;
      resetToDefault();
      return;
    }
    lastDownAtRef.current = now;

    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    startRef.current = { x: e.clientX, width };
    latestWidthRef.current = width;
    setDragging(true);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    const delta =
      edge === 'right' ? e.clientX - startRef.current.x : startRef.current.x - e.clientX;
    applyWidth(clamp(startRef.current.width + delta, min, max));
  };

  const finishDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
    setDragging(false);
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    onWidthCommit?.(latestWidthRef.current);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 32 : 8;
    let next: number | null = null;
    if (e.key === 'ArrowLeft') next = width - step;
    if (e.key === 'ArrowRight') next = width + step;
    if (e.key === 'Home') next = min;
    if (e.key === 'End') next = max;
    if (e.key === 'Enter') next = defaultWidth;
    if (next === null) return;
    e.preventDefault();
    const clamped = clamp(next, min, max);
    applyWidth(clamped);
    onWidthCommit?.(clamped);
  };

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={width}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      title={`拖动调整宽度，双击恢复默认（${defaultWidth}px）`}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={finishDrag}
      onPointerCancel={finishDrag}
      onDoubleClick={resetToDefault}
      onKeyDown={handleKeyDown}
      className="group relative z-20 w-1.5 shrink-0 cursor-col-resize touch-none select-none outline-none"
    >
      {/* 常规状态：极细分隔线 */}
      <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-px bg-slate-200/70 transition-colors group-hover:bg-indigo-300/60" />
      {/* 悬停 / 拖动 / 键盘聚焦时的高亮条 */}
      <div
        className={`absolute inset-y-0 left-1/2 -translate-x-1/2 w-[3px] rounded-full bg-indigo-500 transition-opacity duration-150 ${
          dragging ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100'
        }`}
      />
    </div>
  );
};
