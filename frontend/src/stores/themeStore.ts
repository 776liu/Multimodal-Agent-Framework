import { create } from 'zustand';

type ThemeMode = 'light' | 'dark';

interface ThemeState {
  theme: ThemeMode;
  toggleTheme: () => void;
  setTheme: (theme: ThemeMode) => void;
}

const getInitialTheme = (): ThemeMode => {
  const saved = localStorage.getItem('agent_studio_theme') as ThemeMode | null;
  if (saved === 'light' || saved === 'dark') {
    return saved;
  }
  // 默认暗色模式，更具 AI Studio 科技感
  if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
    return 'light';
  }
  return 'dark';
};

export const useThemeStore = create<ThemeState>((set, get) => {
  const initial = getInitialTheme();
  if (typeof document !== 'undefined') {
    if (initial === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }

  return {
    theme: initial,
    toggleTheme: () => {
      const next: ThemeMode = get().theme === 'dark' ? 'light' : 'dark';
      set({ theme: next });
      localStorage.setItem('agent_studio_theme', next);
      if (next === 'dark') {
        document.documentElement.classList.add('dark');
      } else {
        document.documentElement.classList.remove('dark');
      }
    },
    setTheme: (mode: ThemeMode) => {
      set({ theme: mode });
      localStorage.setItem('agent_studio_theme', mode);
      if (mode === 'dark') {
        document.documentElement.classList.add('dark');
      } else {
        document.documentElement.classList.remove('dark');
      }
    },
  };
});
