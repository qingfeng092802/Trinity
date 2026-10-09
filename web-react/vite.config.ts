import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 后端 FastAPI 地址。本项目**本地这条链路统一 8001**：start.bat 不带参数时起 8001，
// README 的 `BASE` 默认值也是 8001。而 config.py 的 api_port 默认是 **8000**
//（那是 Docker 那条路：compose 映射 ${API_PORT:-8000}:8000），所以手工
// `python -m uvicorn api.main:app` 不带 --port 时前端连不上——代理目标不自动探测。
// 换端口：这一行与后端启动端口必须一起改。
const API_TARGET = 'http://127.0.0.1:8001';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': new URL('./src', import.meta.url).pathname },
  },
  // 把代理目标暴露给前端：顶栏「数据源」标识读它，避免口径与代理不一致
  define: { __API_TARGET__: JSON.stringify(API_TARGET) },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      // SSE 单独一条：EventSource 是长连接，与 /api 混用会被 keep-alive 缓冲干扰
      '/sse': {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/sse/, ''),
      },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        // 拆 vendor：首屏只需 shell + react，图表按需加载，缓存也更友好
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          antd: ['antd', '@ant-design/icons'],
          echarts: ['echarts', 'echarts-for-react'],
          query: ['@tanstack/react-query'],
        },
      },
    },
  },
});
