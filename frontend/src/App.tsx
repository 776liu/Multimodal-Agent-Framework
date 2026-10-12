import React, { useState } from 'react';
import { Sidebar } from './components/sidebar/Sidebar';
import { ChatArea } from './components/chat/ChatArea';
import { AgentInspector } from './components/inspector/AgentInspector';

export const App: React.FC = () => {
  const [inspectorOpen, setInspectorOpen] = useState(true);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-surface-page antialiased font-sans">
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
