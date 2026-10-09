import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

interface TasklistContextValue {
  /** true = 任务列表栏收起，主区拿回整行宽度。 */
  collapsed: boolean;
  toggle: () => void;
}

const TasklistContext = createContext<TasklistContextValue | null>(null);
const KEY = 'trinity-console.tasklist-collapsed';
/** 旧键只在**读取**时兜底一次，写入一律用新键。 */
const LEGACY_KEY = 'agent1-console.tasklist-collapsed';

/** 顶栏的「收起 / 展开任务列表」按钮 ↔ 任务列表栏之间的通道。
 *
 * 按钮属于外壳，列表属于页面（列表数据归页面所有），两者不在同一层，
 * 用 context 而不是把 prop 从 App → 页面 → 面板一路钻过去。
 * 选择结果写 localStorage：宽屏用户收起一次之后，切页/重开都该保持。
 */
export function TasklistProvider({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return (localStorage.getItem(KEY) ?? localStorage.getItem(LEGACY_KEY)) === '1';
    } catch {
      return false;
    }
  });

  const toggle = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(KEY, next ? '1' : '0');
      } catch {
        // 隐私模式下写入会抛；记住本次会话内的状态即可
      }
      return next;
    });
  }, []);

  const value = useMemo(() => ({ collapsed, toggle }), [collapsed, toggle]);
  return <TasklistContext.Provider value={value}>{children}</TasklistContext.Provider>;
}

export function useTasklist(): TasklistContextValue {
  const ctx = useContext(TasklistContext);
  if (!ctx) throw new Error('useTasklist 必须在 TasklistProvider 内使用');
  return ctx;
}
