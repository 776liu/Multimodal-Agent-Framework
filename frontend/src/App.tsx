import React, { useCallback, useEffect, useState } from 'react';
import { Sidebar } from './components/sidebar/Sidebar';
import { ChatArea } from './components/chat/ChatArea';
import { AgentInspector } from './components/inspector/AgentInspector';
import { PanelResizer } from './components/common/PanelResizer';

const SIDEBAR_DEFAULT = 288;
const SIDEBAR_MIN = 200;
const SIDEBAR_MAX = 460;

const INSPECTOR_DEFAULT = 336;
const INSPECTOR_MIN = 260;
const INSPECTOR_MAX = 560;

const SIDEBAR_STORAGE_KEY = 'layout.sidebarWidth';
const INSPECTOR_STORAGE_KEY = 'layout.inspectorWidth';

/** 从 localStorage 读取面板宽度，越界或无效时回落到默认值 */
const readStoredWidth = (
  key: string,
  fallback: number,
  min: number,
  max: number
): number => {
  try {
    const raw = Number(window.localStorage.getItem(key));
    if (!Number.isFinite(raw) || raw <= 0) return fallback;
    return Math.min(max, Math.max(min, Math.round(raw)));
  } catch {
    return fallback;
  }
};

export const App: React.FC = () => {
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(() =>
    readStoredWidth(SIDEBAR_STORAGE_KEY, SIDEBAR_DEFAULT, SIDEBAR_MIN, SIDEBAR_MAX)
  );
  const [inspectorWidth, setInspectorWidth] = useState(() =>
    readStoredWidth(
      INSPECTOR_STORAGE_KEY,
      INSPECTOR_DEFAULT,
      INSPECTOR_MIN,
      INSPECTOR_MAX
    )
  );
  // 视口宽度变化时给面板宽度设上限，避免中间工作区被挤没
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth);

  useEffect(() => {
    const onViewportResize = () => setViewportWidth(window.innerWidth);
    window.addEventListener('resize', onViewportResize);
    return () => window.removeEventListener('resize', onViewportResize);
  }, []);

  const sidebarMax = Math.min(
    SIDEBAR_MAX,
    Math.max(SIDEBAR_MIN, Math.round(viewportWidth * 0.32))
  );
  const inspectorMax = Math.min(
    INSPECTOR_MAX,
    Math.max(INSPECTOR_MIN, Math.round(viewportWidth * 0.36))
  );

  // 实际渲染宽度始终落在允许区间内（视口变窄时同步收紧）
  const effectiveSidebarWidth = Math.min(sidebarWidth, sidebarMax);
  const effectiveInspectorWidth = Math.min(inspectorWidth, inspectorMax);

  const commitSidebarWidth = useCallback((width: number) => {
    try {
      window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(width));
    } catch {
      /* localStorage 不可用时忽略 */
    }
  }, []);

  const commitInspectorWidth = useCallback((width: number) => {
    try {
      window.localStorage.setItem(INSPECTOR_STORAGE_KEY, String(width));
    } catch {
      /* localStorage 不可用时忽略 */
    }
  }, []);

  return (
    <div className="flex min-h-[100dvh] h-[100dvh] w-screen overflow-hidden bg-slate-50 text-slate-800 antialiased font-sans">
      {/* Column 1: Sessions Sidebar (可拖拽调宽，内容自适应) */}
      <Sidebar width={effectiveSidebarWidth} />
      <PanelResizer
        edge="right"
        width={effectiveSidebarWidth}
        min={SIDEBAR_MIN}
        max={sidebarMax}
        defaultWidth={SIDEBAR_DEFAULT}
        onWidthChange={setSidebarWidth}
        onWidthCommit={commitSidebarWidth}
        label="调整会话列表宽度"
      />

      {/* Column 2: Chat & Workspace Area */}
      <ChatArea
        inspectorOpen={inspectorOpen}
        onToggleInspector={() => setInspectorOpen((prev) => !prev)}
      />

      {/* Column 3: Multi-Agent Observability Inspector (可拖拽调宽) */}
      {inspectorOpen && (
        <>
          <PanelResizer
            edge="left"
            width={effectiveInspectorWidth}
            min={INSPECTOR_MIN}
            max={inspectorMax}
            defaultWidth={INSPECTOR_DEFAULT}
            onWidthChange={setInspectorWidth}
            onWidthCommit={commitInspectorWidth}
            label="调整 Agent 观测看板宽度"
          />
          <AgentInspector width={effectiveInspectorWidth} />
        </>
      )}
    </div>
  );
};

export default App;
