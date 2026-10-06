/// <reference types="vite/client" />

/** 由 vite.config.ts 的 define 注入：后端真实地址，用于顶栏「数据源」标识。
 *  单一事实来源是 vite 代理配置，避免再出现「代理打 8001、页头写 8000」这种不一致。
 */
declare const __API_TARGET__: string;
