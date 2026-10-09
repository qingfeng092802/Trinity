import { useEffect, useState } from 'react';

/** 断点 hook。JS 断点必须与 src/index.css §13 的媒体查询保持一致：
 *  - `useIsMid`     1180px：任务列表栏（第二栏）收进抽屉
 *  - `useIsCompact` 1024px：侧栏切抽屉（CSS 里同一断点把 .app-sider 平移出去）
 *  - `useIsNarrow`  768px：出现底部标签栏
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window === 'undefined' ? false : window.matchMedia(query).matches,
  );

  useEffect(() => {
    const mq = window.matchMedia(query);
    const onChange = () => setMatches(mq.matches);
    onChange();
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, [query]);

  return matches;
}

/** 1180px：第二栏收进抽屉。
 *  必须与 index.css 里 `.task-col--drawer` 的媒体查询同值 —— 否则会出现
 *  「CSS 已经切抽屉、JS 还在渲染常驻栏」的错位。 */
export function useIsMid(): boolean {
  return useMediaQuery('(max-width: 1180px)');
}

export function useIsCompact(): boolean {
  return useMediaQuery('(max-width: 1024px)');
}

export function useIsNarrow(): boolean {
  return useMediaQuery('(max-width: 768px)');
}
