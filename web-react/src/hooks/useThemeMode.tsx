import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

import { applyThemeVars, systemPrefersDark } from '../theme';
import type { ThemeMode } from '../theme';

const STORAGE_KEY = 'trinity-console.theme';
/** 旧键只在**读取**时兜底一次，写入一律用新键，
 *  这样升级上来的用户不会丢掉已选的明暗主题。 */
const LEGACY_STORAGE_KEY = 'agent1-console.theme';

interface ThemeModeContextValue {
  mode: ThemeMode;
  setMode: (mode: ThemeMode) => void;
  toggle: () => void;
}

const ThemeModeContext = createContext<ThemeModeContextValue | null>(null);

/** 初始主题：本地存储优先，其次跟随系统。
 *
 *  `main.tsx` 在首次渲染前会调用它并 `applyThemeVars`，避免深色用户看到一闪而过的白屏。
 */
export function resolveInitialMode(): ThemeMode {
  try {
    const saved =
      localStorage.getItem(STORAGE_KEY) ?? localStorage.getItem(LEGACY_STORAGE_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
  } catch {
    // 隐私模式下 localStorage 可能抛异常，忽略即可
  }
  return systemPrefersDark() ? 'dark' : 'light';
}

export function ThemeModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(resolveInitialMode);

  useEffect(() => {
    applyThemeVars(mode);
    try {
      localStorage.setItem(STORAGE_KEY, mode);
    } catch {
      // 同上
    }
  }, [mode]);

  const setMode = useCallback((next: ThemeMode) => setModeState(next), []);
  const toggle = useCallback(() => setModeState((prev) => (prev === 'dark' ? 'light' : 'dark')), []);

  const value = useMemo(() => ({ mode, setMode, toggle }), [mode, setMode, toggle]);

  return <ThemeModeContext.Provider value={value}>{children}</ThemeModeContext.Provider>;
}

export function useThemeMode(): ThemeModeContextValue {
  const ctx = useContext(ThemeModeContext);
  if (!ctx) throw new Error('useThemeMode 必须在 ThemeModeProvider 内使用');
  return ctx;
}
