import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';
// 初始化主题（跟随系统浅色/深色偏好，无手动切换按钮）
import './stores/themeStore';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
