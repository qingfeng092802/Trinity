import { Suspense, lazy } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';

import AppShell from './components/AppShell';
import ErrorBoundary from './components/ErrorBoundary';
import { Skel } from './components/ui';

/** 四页各自成 chunk。
 *
 * 为什么必须动态 import：`echarts`（gzip 348,946 B）只有 /eval 用得到，但它原先经
 * 静态 import 链进了入口图 ⇒ 落在 index.html 的 modulepreload 里，四页一起为一张柱状图
 * 买单（2026-09-25 走查 EV-03）。摘掉之后 /tasks 首屏 JS 少 44.5%，/eval 才多发一个请求。
 *
 * ⚠️ 这条纪律的**存在性**由 `tools/uicheck/bundle.cjs` 钉着（读 dist 产物，不读源码）：
 * 谁把某一页改回静态 import、或者把 /eval 专属的重依赖挪进 `AppShell`，那条门槛就翻红。
 * 2026-09-26 加第四页（/knowledge）时它同样只进自己的 chunk —— 新页面若哪天 import 了
 * 图表，别忘了它也会顺带把 echarts 拉进那一页的首屏。
 */
const TaskLogPage = lazy(() => import('./pages/TaskLogPage'));
const TraceReplayPage = lazy(() => import('./pages/TraceReplayPage'));
const EvalAblationPage = lazy(() => import('./pages/EvalAblationPage'));
const KnowledgePage = lazy(() => import('./pages/KnowledgePage'));

/** chunk 在途时的占位：只填主内容区，外壳（图标栏 / 顶栏 / 底部标签栏）已经在下面。
 *  版式照各页自己的页头（标题一条 + 说明一条 + 主体一块），高度不铺满 ——
 *  主内容是这一列的最后一个元素，它变高不会推动任何已渲染的东西，所以不引入 CLS。
 */
function PageFallback() {
  return (
    <div className="page-main page-fallback" role="status" aria-busy="true">
      <Skel w="min(20rem, 55%)" h={24} />
      <Skel w="min(30rem, 80%)" h={13} style={{ marginTop: 10 }} />
      <Skel w="100%" h="12rem" r={10} style={{ marginTop: 18 }} />
      <span className="sr-only">正在加载本页…</span>
    </div>
  );
}

export default function App() {
  const location = useLocation();
  return (
    <AppShell>
      {/* key= 路径：切页即重建边界，上一页的兜底不会赖在下一页上 */}
      <ErrorBoundary key={location.pathname} label="页面">
        {/* Suspense 放在边界**内侧**：chunk 拉取失败要落到 ErrorBoundary 那条
            「刷新页面」的出口上，放外侧错误就一路冒到最外层、只剩白屏。 */}
        <Suspense fallback={<PageFallback />}>
          <Routes>
            <Route path="/tasks" element={<TaskLogPage />} />
            <Route path="/trace" element={<TraceReplayPage />} />
            <Route path="/eval" element={<EvalAblationPage />} />
            <Route path="/knowledge" element={<KnowledgePage />} />
            <Route path="*" element={<Navigate to="/tasks" replace />} />
          </Routes>
        </Suspense>
      </ErrorBoundary>
    </AppShell>
  );
}
