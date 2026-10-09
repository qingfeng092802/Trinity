import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  applyModelOverride,
  fetchModels,
  postModelKey,
  resetModelOverride,
  validateModelKey,
} from '../api/client';
import { AGENT_OPTIONS_QUERY_KEY } from './useAgentOptions';
import type { ModelKeyProbeView, ModelListResponse } from '../types';

/** 模型注册表的查询键（面板与胶囊共用同一份缓存 ⇒ 只有一个地方能"是新的"）。 */
export const MODELS_QUERY_KEY = ['models'] as const;

/** 拉``GET /models``的原始结果（可能为 ``null`` = 还在拉 / 拉失败 / mock 模式）。
 *
 * 与 ``useToolSpecs`` 同一纪律：**拉不到就当没有** —— 调用方把那一条整条不渲染，
 * 绝不回落到一份写死的模型清单：上一版的 bug 正是「选项抄在 ``src/mock/taskMock.ts``
 * 里、后端没有对应字段」，回落等于把同一个谎换个地方再写一遍。
 *
 * 2026-09-26 起改用 React Query（原来是模块级 ``inflight`` 合流）：
 * 换模型的写端点成功后要能把新状态**推给所有读它的人**（胶囊、面板、composer 那行读数）。
 * 手动 ``useState`` 那份做不到 —— 它只在自己挂载时拉一次，改完之后胶囊会继续显示旧模型，
 * 而"界面显示的不是生效的"正是这条链最不能出的错（方案 T-1 / L-5 第 2 条）。
 */
export function useModelRegistry(): ModelListResponse | null {
  const { data } = useQuery({ queryKey: MODELS_QUERY_KEY, queryFn: fetchModels });
  return data ?? null;
}

/** 胶囊那行读数用的包装：``items`` 为空（mock / 老后端）时也当"没有"，整条不渲染。 */
export function useModels(): ModelListResponse | null {
  const registry = useModelRegistry();
  return registry && registry.items.length ? registry : null;
}

/** 写侧成功后一起要做的事：整份状态回缓存 + 让「运行配置」面板那一屏重拉。
 *
 * 第二半是 2026-09-27 补的：``GET /config/agent-options`` 的 ``models.roles`` 读的
 * 就是这份运行时覆盖（后端 :mod:`api.routes.config` 里那两行 ``override.model_large``），
 * 而 ``RunConfigPanel`` 缓存着它 —— 不 invalidate 的话会出现
 * 「齿轮那里已经换成了 glm-4.6，运行配置面板还印着 deepseek-chat」，
 * 同屏两个模型名（AE-06 那条判据量的是这个，不是"有没有渲染"）。
 *
 * ⚠️ 只 invalidate，**不许**在这里顺手 ``setQueryData`` 一份前端算的 agent-options：
 * 那一屏的默认值 / 界 / 预设比"两个模型名"多得多，猜一半比不猜更糟。 */
function settle(client: ReturnType<typeof useQueryClient>, state: ModelListResponse): void {
  client.setQueryData<ModelListResponse>(MODELS_QUERY_KEY, state);
  void client.invalidateQueries({ queryKey: AGENT_OPTIONS_QUERY_KEY });
}

/** 应用一次换模型。成功就把服务端给的**整份新状态**写回缓存 ——
 *  界面显示的必须是响应给的，不许前端自己改完自己显示（方案 T-7）。 */
export function useModelOverrideMutation(onDone?: (state: ModelListResponse) => void) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: applyModelOverride,
    onSuccess: (ack) => {
      settle(client, ack.state);
      onDone?.(ack.state);
    },
  });
}

/** 撤掉覆盖（回落 .env）。同一份缓存写入逻辑。**不清 Key**（后端那条注释同义）。 */
export function useModelOverrideReset() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: resetModelOverride,
    onSuccess: (ack) => settle(client, ack.state),
  });
}

/** 把某家的 Key 放进本次进程（传空串 = 撤回）。
 *
 * 缓存里写的是响应给的**整份状态**，里面没有任何字段装得下那串值 ——
 * 所以"不进 react-query 缓存"这条约束靠的是响应本身没有那个字段，
 * 不是靠这里少写一行 ``setQueryData``（少写那行的话缓存里会留下**上一次**的已配置状态，
 * 那才是说谎）。明文从头到尾只存在于调用方组件的一个 state 里。 */
export function useModelKeyMutation(onDone?: (state: ModelListResponse) => void) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ provider, apiKey }: { provider: string; apiKey: string }) =>
      postModelKey(provider, apiKey),
    onSuccess: (ack) => {
      settle(client, ack.state);
      onDone?.(ack.state);
    },
  });
}

/** 校验一把 Key（零 token 的 ``GET {base_url}/models``）。
 *
 * 刻意**不写任何缓存**：校验通过不等于用户要用它，那是一颗单独的「应用」按钮的职责。
 * 返回的就是后端那句 ``detail``（成功=拿到几个模型，失败=供应商原话），
 * 调用方原样落地，不改写 —— 与 F-1 那条纪律同一个理由：谁报的谁说得出细节。 */
export function useModelKeyProbe() {
  return useMutation<ModelKeyProbeView, Error, { provider: string; apiKey: string }>({
    mutationFn: ({ provider, apiKey }) => validateModelKey(provider, apiKey),
  });
}
