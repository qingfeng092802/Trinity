import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App as AntApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';

import App from './App';
import { RefreshProvider } from './hooks/useRefresh';
import { RunConfigProvider } from './hooks/useRunConfig';
import { TasklistProvider } from './hooks/useTasklist';
import { ThemeModeProvider, resolveInitialMode, useThemeMode } from './hooks/useThemeMode';
import { ANTD_THEME, applyThemeVars } from './theme';
import './index.css';

// 首帧渲染前先把主题变量落到 <html>：深色用户不会先看到一闪的白屏
applyThemeVars(resolveInitialMode());

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // 控制台数据变化快，但不需要实时：30s 内复用缓存，避免切页就打后端
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

/** 主题态要在 ConfigProvider 之上，所以抽一层 Root。 */
function Root() {
  const { mode } = useThemeMode();
  return (
    <ConfigProvider theme={ANTD_THEME[mode]} locale={zhCN}>
      <AntApp>
        <QueryClientProvider client={queryClient}>
          <RefreshProvider>
            <BrowserRouter>
              <TasklistProvider>
                {/* 运行配置草稿的唯一宿主（U-5）：composer 的两颗快捷开关与
                    「运行配置」面板读写**同一份** state。刻意不落 localStorage ——
                    这是一份"下一次提交要什么"的草稿，不是一条阅读偏好；
                    预算/超时这类东西被静默带到下一次会话里，比丢掉更糟。 */}
                <RunConfigProvider>
                  <App />
                </RunConfigProvider>
              </TasklistProvider>
            </BrowserRouter>
          </RefreshProvider>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeModeProvider>
      <Root />
    </ThemeModeProvider>
  </StrictMode>,
);
