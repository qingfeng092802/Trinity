import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

interface RefreshContextValue {
  /** 自增令牌：页面把它放进依赖数组即可被动刷新（含手写 fetch 的页面）。 */
  token: number;
  refresh: () => void;
}

const RefreshContext = createContext<RefreshContextValue | null>(null);

/** 顶栏「刷新」按钮的广播通道。
 *
 * 四个页面的数据来源不完全一致（有的走 TanStack Query，有的走手写 fetch），
 * 用自增令牌统一，避免为了刷新一个按钮把全部页面改成同一套数据层。
 */
export function RefreshProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState(0);
  const refresh = useCallback(() => setToken((t) => t + 1), []);
  const value = useMemo(() => ({ token, refresh }), [token, refresh]);
  return <RefreshContext.Provider value={value}>{children}</RefreshContext.Provider>;
}

export function useRefresh(): RefreshContextValue {
  const ctx = useContext(RefreshContext);
  if (!ctx) throw new Error('useRefresh 必须在 RefreshProvider 内使用');
  return ctx;
}
