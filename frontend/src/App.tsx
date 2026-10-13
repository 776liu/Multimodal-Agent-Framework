import React, { useState } from 'react';
import { Sidebar } from './components/sidebar/Sidebar';
import { ChatArea } from './components/chat/ChatArea';
import { AgentInspector } from './components/inspector/AgentInspector';

export const App: React.FC = () => {
  const [inspectorOpen, setInspectorOpen] = useState(true);

  return (
    <div className="flex min-h-[100dvh] h-[100dvh] w-screen overflow-hidden bg-slate-50 dark:bg-slate-950 text-slate-800 dark:text-slate-100 antialiased font-sans">
      {/* Column 1: Sessions Sidebar */}
      <Sidebar />

      {/* Column 2: Chat & Workspace Area */}
      <ChatArea
        inspectorOpen={inspectorOpen}
        onToggleInspector={() => setInspectorOpen((prev) => !prev)}
      />

      {/* Column 3: Multi-Agent Observability Inspector */}
      {inspectorOpen && <AgentInspector />}
    </div>
  );
};

export default App;
