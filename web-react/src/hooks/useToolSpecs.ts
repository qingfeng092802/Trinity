import { useEffect, useState } from 'react';
import { fetchTools } from '../api/client';
import type { ToolSpecView } from '../types';

/** 拉一次工具注册表，按名字建索引。
 *
 * 只给「展示层」用：字典里没收录的工具，靠这里的注册表说明兜底。
 * 拉不到就当没有 —— 工具卡片仍然完整可读，不打断用户，也不弹错。
 *
 * 注册表在一次会话里是静态的，所以请求在模块级合流：StrictMode 双挂载
 * 只发一次（实测双挂载会打两发 /api/tools），失败则不缓存、下次挂载可重试。
 */
let inflight: Promise<ToolSpecView[]> | null = null;

function loadOnce(): Promise<ToolSpecView[]> {
  if (!inflight) {
    inflight = fetchTools().then(
      (items) => items,
      () => {
        inflight = null;
        return [] as ToolSpecView[];
      },
    );
  }
  return inflight;
}

export function useToolSpecs(): Map<string, ToolSpecView> {
  const [byName, setByName] = useState<Map<string, ToolSpecView>>(() => new Map());

  useEffect(() => {
    let alive = true;
    loadOnce().then((items) => {
      if (alive && items.length) setByName(new Map(items.map((s) => [s.name, s])));
    });
    return () => {
      alive = false;
    };
  }, []);

  return byName;
}
