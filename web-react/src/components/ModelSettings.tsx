import { useEffect, useMemo, useState } from 'react';

import { App, AutoComplete, Button, Input, Select, Tooltip } from 'antd';
import {
  CheckCircleOutlined,
  DownOutlined,
  InfoCircleOutlined,
  LockOutlined,
} from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';

import { describeFetchError } from '../api/client';
import { fetchKnowledgeOverview } from '../api/client';
import {
  useModelKeyMutation,
  useModelKeyProbe,
  useModelOverrideMutation,
  useModelOverrideReset,
  useModelRegistry,
} from '../hooks/useModels';
import type { ModelCatalogEntry, ModelListResponse, ProviderKeyView } from '../types';

/** 右上角「模型设置」弹层的内容（换模型方案 §2 L-4）。
 *
 * 为什么整个面板是**懒加载**的（``AppShell`` 里 ``React.lazy`` 引进来）：
 * ``AppShell`` 在入口 chunk 里，这里要用的 ``AutoComplete`` / ``Select`` 都会跟着进入口，
 * 而 99% 的会话从不打开这个面板。门禁 ``tools/uicheck/bundle.cjs`` 量的是入口 gzip。
 *
 * 三条硬规矩（都是这条链上"看起来正常但会骗人"的形状）：
 *
 * 1. **候选只来自 ``GET /models`` 的 ``catalog``**，前端一份模型名都不写（方案 T-7）。
 *    读不到 ``catalog`` ⇒ 整块改口说"这一趟没读到候选清单"，并且**不印半截话**：
 *    老进程（后端不带 ``--reload``，新字段要重启才在）会返回没有这些字段的响应。
 * 2. **应用之后显示的是响应给的那份状态**，不是前端自己拼的（``useModelOverrideMutation``
 *    把 ``ack.state`` 写回查询缓存，胶囊与面板同时跟着变）。
 * 3. **Key 输入框是"只进不出"的那一个**（2026-09-27 改了这一条，原来是"页面不收 Key"）：
 *    值只走 ``POST /models/key`` 的 body —— 不进 URL/query、不进 react-query 缓存
 *    （响应里根本没有装得下它的字段）、不写 localStorage、不落盘，后端重启后回落到 ``.env``。
 *    屏幕上还有一条更严的：**失焦即真空串**（见 :func:`KeySection` 的那段注释），
 *    为的是录屏与投屏时不会被旁边的人看见半拉子 Key。
 */

/** 档位 → 人话。与后端的 ``large`` / ``small`` 同一集合，不另造第三种取值。
 *
 * 2026-09-29 改名：``大档（强模型）/ 小档（快模型）`` ⇒ ``决策模式 / 执行模式``。
 * 只换**显示在屏幕上的名字** —— 内部变量、``tier`` 枚举、后端 ``config.py`` 的字段名
 * 一个都没动（改那些会把界面口径偷渡进协议）。「决策 / 执行」这对词是从**谁用它**来的：
 * 一档是"拿主意"的三个角色，另一档是"干活"的两个，与下面那行「角色绑定」同一份事实，
 * 两处必须说同一句话，否则就是同屏两份真源。 */
const TIER_LABEL: Record<'large' | 'small', string> = { large: '决策模式', small: '执行模式' };

/** 两个档位各绑哪些编排角色 —— 这一行是**界面上唯一一处**说清"两档分别管谁"的地方。
 *
 * 为什么缩成一行小字而不是那张五行表：后端 ``POST /models/override`` 只接受两个档位，
 * 没有 per-role 这条语义 ⇒ 那五行**永远不可能不一致**（第二列只是第一列的展开）。
 * 信息量等于零的五张卡，占的地方却比"这一屏真能改的那两行"还大。
 * ⚠️ 串里的 ``·`` 一律写在文本里，不靠相邻 span 之间的空白（textContent 会糊成
 *    「Judge执行模式」）。角色名照抄后端的 ``role`` 字段，不译中文 ——
 *    日志、轨迹、``/config/agent-options`` 里都叫这个名，译了就对不上号。 */
const ROLE_BINDING =
  '角色绑定：决策模式 → Planner / Reviewer / Judge · 执行模式 → Executor / Extract';

/** 五个角色的中文职责（ⓘ 浮层里那张表）。与上面那一行同源，只是把"管谁"展开成"干什么"。 */
const ROLE_DUTY: [string, string][] = [
  ['Planner', '拆解任务、决定先做哪一步'],
  ['Reviewer', '复核执行结果、写最终答案'],
  ['Judge', '评审打分，判断要不要重跑'],
  ['Executor', '按计划调用工具、产出中间结果'],
  ['Extract', '从文档里抽结构化字段'],
];

/** 候选行**渲染出来的两行**（2026-09-27 从"一整串"拆成两行）：
 *  第一行只有干净的模型 id，第二行是展示名（版本号在那儿）+ 阶梯单价 + 缺 Key 提示。
 *
 * 为什么拆行而不是把弹层加宽到塞得下整串：这一屏要读的是**候选之间怎么挑**，
 * 主名被尾巴挤掉就等于看不见（原来那串在 300px 弹层里必然截断）。
 * ⚠️ 三段串一律**原样落屏**：``display_name`` / ``tiers_text`` / ``key_env_var`` 都来自响应，
 *    前端自己排一次数字就多一处能把"最低档"印成"这个模型的价"的地方（方案 T-3）。
 *    阶梯那一长串（``1/3 元（输入 ≤32,000） · 2/6 元（输入 ≤128,000）``）也在第二行 ——
 *    AC-1b 判的就是"整档表摊开"，缩成一行看不见的东西不算摊开。
 * ⚠️ 没配 Key 的行**照样可选**（只标注不挡）：判定权在后端，它才知道环境变量。 */
function OptionLines({ entry }: { entry: ModelCatalogEntry }) {
  const sub = [
    entry.display_name === entry.id ? null : entry.display_name,
    entry.tiers.length > 1 ? entry.tiers_text : `${entry.tiers_text} 每 100 万 token`,
    entry.key_configured ? null : `未配 Key · 需 ${entry.key_env_var}`,
  ].filter(Boolean);
  return (
    <span className="ms-opt">
      <span className="ms-opt-name">{entry.id}</span>
      <span className="ms-opt-sub">{sub.join(' · ')}</span>
    </span>
  );
}

/** 这一行**可被搜索**的文本 —— 与上面渲染的那两行同源，但不进 DOM。
 *
 * ⚠️ 为什么不直接用 ``option.label`` 当搜索串（原来就是这么写的）：``label`` 现在是
 *    ReactNode，``String(label)`` 得到的是 ``[object Object]`` ⇒ 打字过滤会**静默变成
 *    "一条都不匹配"**，而下拉看起来只是"筛得严"，不像坏了。所以搜索串单独算一份，
 *    并且 ``filterOption`` 改成按 ``value`` 回查 catalog（同一个 :func:`OptionLines` 的输入）。 */
function optionSearchText(entry: ModelCatalogEntry): string {
  return [
    entry.id,
    entry.display_name,
    entry.tiers_text,
    entry.key_configured ? '' : entry.key_env_var,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}

function currentTier(registry: ModelListResponse | null, tier: 'large' | 'small'): string {
  const item = registry?.items.find((i) => i.tier === tier);
  if (item) return item.id;
  const override = registry?.override;
  if (!override) return '';
  return tier === 'large' ? override.model_large : override.model_small;
}

/** 一家 Key 状态的**两半**：短状态 + 「来源」那一句（2026-09-27 把原来那一整句拆成两段）。
 *
 * 原来 :func:`providerKeySentence` 一句全包（``未单独配置；当前跟着 .env 的 LLM_API_KEY（网关档）``），
 * 在五行的状态清单里每行都要占两行高。拆开之后一行放得下：
 * ``● DeepSeek（已配置） · 来源：环境变量 LLM_API_KEY · 3 个候选 · 分高峰/低谷``。
 *
 * ⚠️ **状态跟着那枚点，来源跟着那把 Key** —— 这条分法是 U-5 拍下来的，不许合并：
 * 点说的是"这一家现在发得出请求"（``key_configured``），来源说的是"发得出靠的是哪一把"。
 * 网关档下这两件事**故意不同**（点绿、来源写"跟着 .env 的 LLM_API_KEY"）——
 * 让状态改按 ``own_key_configured`` 说"未配置"，就回到当年那句"已配置"两个意思的老病；
 * 让状态只说"已配置"而不说来路，则是把"用的其实是网关那把"这件事藏起来。
 * 前端不重新判一遍路由规则（那规则只有 :func:`core.llm.runtime.route` 一份）。 */
function keyStatus(p: ProviderKeyView): string {
  return p.key_configured ? '已配置' : '未配置';
}

function keySource(p: ProviderKeyView): string {
  const own = p.own_key_configured ?? p.key_configured;
  const ownVar = p.own_key_env_var ?? p.key_env_var;
  if (p.env_channel) {
    /* 两者相同（这家本来就只有一把）时不必提醒"那把不会被用到"，说了反而绕。 */
    const unused = own && p.own_key_env_var && p.own_key_env_var !== p.key_env_var;
    return `跟着 .env 的 ${p.key_env_var}（网关档${unused ? `，填在 ${ownVar} 的那把不会被用到` : ''}）`;
  }
  if (p.key_source === 'runtime') return `本次进程里填的（重启后回落到 ${ownVar}）`;
  if (own) return `环境变量 ${ownVar}`;
  return `需环境变量 ${ownVar}`;
}

/** Key 那一栏：选一家 → 填 → 校验 → 应用（全部只活在本进程）。
 *
 * ⚠️ :param:`idPrefix` 不是装饰。这一份组件现在有两个宿主（顶栏齿轮的浮层、
 * 「设置」中心的「模型」项），两边都带 ``#model-key-input`` 这种**写死的 id** ⇒
 * 同时挂载就是重复 id：``document.getElementById`` 只会拿到文档里第一个，
 * 于是探针（和读屏软件）量的可能不是它声称在量的那一份。宿主各给一个前缀即可。
 *
 * 三条与"值"有关的规矩，每条都对应用户明确点过的形状：
 *
 * 1. **失焦即真空串**：``shown`` 是输入框的值，blur 时置为 ``''``（不是切回掩码显示，
 *    是真的空），再聚焦也**不回填** —— 录屏停在这块面板上时 DOM 里取不到那串东西。
 *    ⚠️ 但 :data:`draft` 不清：点「校验」那颗按钮会先触发 blur 再触发 click，
 *    连草稿一起清掉的话这颗按钮永远拿不到值（功能就没了）。
 *    所以留下的是"内存里一份、屏幕上一份"，屏幕上那份是空的；
 *    而"不回填"这条判据（AE-02）量的正是 ``shown`` 那一份。
 * 2. **只走 POST body**：URL 是常量 ``/models/key``，:func:`postKeyJson` 里还自证了一次。
 * 3. **切换供应商 = 丢掉手上那把**：Key 只对选中的那家生效，留着会出"给智谱填的
 *    其实发给了千问"这种最难查的错。 */
function KeySection({
  providers,
  defaultProvider,
  idPrefix = '',
  onDirtyChange,
  resetSignal = 0,
}: {
  providers: ProviderKeyView[];
  defaultProvider: string;
  idPrefix?: string;
  /** 手上有没有"填了还没提交"的那把 Key —— 传出去是因为底栏那枚 dirty 小圆点
   *  住在 ``RunConfigPanel`` 里，而草稿住在这一层（见下面 ``useEffect`` 那条注释）。 */
  onDirtyChange?: (dirty: boolean) => void;
  /** 递增即"把这一栏清回出厂态"（底部那颗「恢复默认配置」点一次 +1）。 */
  resetSignal?: number;
}) {
  const { message } = App.useApp();
  /** 此刻在配哪一家（供应商码，与 ``GET /models`` 的 ``providers[].provider`` 同一集合）。 */
  const [picked, setPicked] = useState('');
  /** 明文只活在这里：不进 URL、不进缓存、不进 localStorage、不发往任何读端点。 */
  const [draft, setDraft] = useState('');
  /** 输入框**此刻显示**的值 —— 失焦就空，永不回填。 */
  const [shown, setShown] = useState('');
  const applyKey = useModelKeyMutation();
  const probe = useModelKeyProbe();

  useEffect(() => {
    if (!providers.length) {
      setPicked('');
      return;
    }
    setPicked((cur) =>
      cur && providers.some((p) => p.provider === cur)
        ? cur
        : providers.find((p) => p.provider === defaultProvider)?.provider ?? providers[0].provider,
    );
  }, [providers, defaultProvider]);

  /** 草稿的"有/没有"报给外面（底栏那枚小圆点）。
   *
   * ⚠️ 报的是 ``draft`` 不是 ``shown``：``shown`` 一 blur 就空，
   *    拿它当"改没改过"会把"填了然后点了别处"读成"没改过" —— 而那一刻恰恰是
   *    **唯一需要**小圆点亮着的时刻（屏幕上没字、内存里有值）。 */
  useEffect(() => {
    onDirtyChange?.(draft.trim().length > 0);
  }, [draft, onDirtyChange]);

  /** 「恢复默认配置」⇒ 手上那把草稿一并丢掉（清的是内存里那份，屏幕上那份本来就是空的）。 */
  useEffect(() => {
    if (!resetSignal) return;
    setDraft('');
    setShown('');
  }, [resetSignal]);

  const selected = providers.find((p) => p.provider === picked) ?? null;
  /* 网关档下**不画输入框**（U-5 拍的那一条）：填了也不会被用到，
     给一个"能填、会发、什么都不改变"的框，比不给更糟 —— 那正是 R-04 那一类形状。 */
  const gateway = selected?.env_channel === true;
  const canSend = !gateway && draft.trim().length > 0;

  const swapProvider = (next: string) => {
    setPicked(next);
    setDraft('');
    setShown('');
  };

  const runProbe = () => {
    if (!canSend) return;
    probe.mutate(
      { provider: picked, apiKey: draft.trim() },
      {
        onError: (err) => {
          /* 422 的``message``是后端那句"这把 Key 不会被用到…"；网络错误另有其话。
             一律原样落地，不改写（F-1 纪律）。 */
          void message.error(describeFetchError(err).message || '校验请求未能发出');
        },
      },
    );
  };

  const commit = () => {
    if (!canSend) return;
    applyKey.mutate(
      { provider: picked, apiKey: draft.trim() },
      {
        onSuccess: (ack) => {
          setDraft('');
          setShown('');
          /* 保持选中的那一家不动：切换 ``picked`` 会让"刚才填的是给谁的"这句话错位，
             而下面那份列表会随 ``ack.state`` 自己变绿点与来源。 */
          void message.success(ack.message);
        },
        onError: (err) => void message.error(describeFetchError(err).message || '填 Key 失败'),
      },
    );
  };

  const revoke = () => {
    applyKey.mutate(
      { provider: picked, apiKey: '' },
      {
        onSuccess: (ack) => void message.info(ack.message),
        onError: (err) => void message.error(describeFetchError(err).message || '撤 Key 失败'),
      },
    );
  };

  const probeView = probe.data;

  return (
    <div className="ms-keybox">
      {/* 标题只留四个字，那三条约束搬进 ⓘ：整句摆在标题位上会把这一栏的"标题 / 表单"
          层级压平（同屏另有一处 ⓘ 讲的是向量模型，两处用同一枚图标与同一族样式）。
          ⚠️ 那句话**不能只在浮层里**活着过判据：AE-1 悬停取的是这颗 ⓘ 自己的浮层
          （顺 ``aria-describedby``），所以这里不许把它降级成 title 属性之类的读不到东西。 */}
      {/* 与「模型配置」「向量模型」同一族小标题（2026-09-29）：三段的标题必须是**同一种记号**，
          否则读出来的是"这一段比那两段高一档"。 */}
      <p className="ms-section-title">
        API Key 配置
        <Tooltip title="填了只在本进程生效，重启回落 .env；页面不回显任何 Key。">
          <span className="ms-info ms-key-info" tabIndex={0} aria-label="API Key 的生效范围">
            <InfoCircleOutlined />
          </span>
        </Tooltip>
      </p>
      <div className="ms-key-row">
        <label className="ms-key-label" htmlFor={`${idPrefix}model-key-provider`}>
          供应商
        </label>
        <Select
          id={`${idPrefix}model-key-provider`}
          className="ms-key-select"
          size="small"
          variant="borderless"
          value={picked || undefined}
          placeholder="选一家"
          onChange={swapProvider}
          options={providers.map((p) => ({
            value: p.provider,
            label: `${p.display_name}（${keyStatus(p)}） · 来源：${keySource(p)}`,
          }))}
        />
      </div>

      {!selected ? (
        <p className="model-settings-note">这一趟没读到任何一家的状态，所以这里不给输入框。</p>
      ) : gateway ? (
        <p className="ms-key-gateway" role="note">
          现在所有请求都走 .env 的端点与 Key（<code>{selected.key_env_var}</code>），
          {selected.display_name} 这把不会被用到 —— 所以这里不给输入框。
          要按家分 Key，请把 <code>LLM_PROVIDER</code> 改成那家的名字再重启后端。
        </p>
      ) : (
        <>
          <div className="ms-key-row">
            <label className="ms-key-label" htmlFor={`${idPrefix}model-key-input`}>
              API Key
            </label>
            <Input.Password
              id={`${idPrefix}model-key-input`}
              className="ms-key-input"
              size="small"
              value={shown}
              /* ⚠️ 三个属性都是这条链上的洞：``autoComplete="new-password"`` 让浏览器
                 既别填也别**存**（存进密码管理器 = 那把 Key 落在浏览器的长期存储里，
                 与"不落盘"这条约束的精神相反）；不 ``paste`` 关是因为粘进来也一样会被
                 blur 清空，没有额外风险，关掉只会难为用户。 */
              autoComplete="new-password"
              /* 2026-09-29：占位符改成**一句固定话术**，不再按"这家配没配过 Key"分两种。
                 原来那两句里塞了环境变量名，于是那一行变成"半个状态读数" ——
                 而同一屏里「供应商」那一格已经写着状态与来路（选中的那家**就显示在框里**），
                 同屏两份同数是这一屏明确不要的形状。生效范围（仅本次运行 / 重启恢复）
                 是这一格**唯一该说**的事，因为它在别处没有第二个读点。 */
              placeholder="输入新 Key 仅本次运行生效，重启恢复环境变量"
              /* 「校验」从下面那排按钮搬进**输入框右端**（图标按钮 + tooltip）：
                 它管的就是这一格里那串值，摆在贴着它的位置才不用"往上找是哪颗"。
                 ⚠️ 走 ``suffix`` 而不是在行尾另起一个元素：后者会把输入框挤出这一行的
                    右边缘（AD-70 量的是"控件撑到行尾"），而 AntD 的 ``Input.Password``
                    自己会把 ``suffix`` 排在眼睛图标之后 —— 眼睛在前、校验在后，各管一件事。
                 ⚠️ 图标按钮**必须有** ``aria-label``：这一颗上没有文字，
                    光有一个图标读屏念出来的是"按钮"，等于没名字。 */
              suffix={
                <Tooltip title="拿这一把打一次真实请求，看端点认不认（3 秒超时）">
                  <Button
                    className="ms-key-probe"
                    type="text"
                    size="small"
                    aria-label="校验"
                    disabled={!canSend}
                    loading={probe.isPending}
                    onClick={runProbe}
                    icon={<CheckCircleOutlined />}
                  />
                </Tooltip>
              }
              onChange={(e) => {
                setShown(e.target.value);
                setDraft(e.target.value);
              }}
              onBlur={() => setShown('')}
              onPressEnter={runProbe}
            />
          </div>
          <div className="ms-key-row">
            {/* Base URL **视觉降权**：端点不是让用户填的（这格只读），
                写成一个跟「API Key」同级的黑标签会读成"这里也要填一项"。 */}
            {/* 不另起一个"更浅"的类：``.ms-key-label`` 本来就是 11px 灰字（--text-3），
                再压一档要么靠 opacity（那是**障眼法** —— 判据读 computed color 读不到它，
                于是"看着更浅"而 AA 其实已经掉了），要么换一个比 --text-3 更浅的 token，
                那一个在这一屏的两个主题下都过不了 AA。降权由**位置**（在 Key 输入框下方）
                与它自己只读这两件事完成，不再加一层视觉。 */}
            <span className="ms-key-label">Base URL</span>
            <Input
              className="ms-key-baseurl"
              size="small"
              readOnly
              value={selected.base_url}
              /* 那家的 ``base_url_env_var`` 可以是空串（DeepSeek 在注册表里就没有单独字段，
                 端点就是 .env 的 ``LLM_BASE_URL``）—— 句子必须跟着换，否则这里会出现
                 「请设环境变量  再重启」那种半截话（探针的第一版就量到过一个空格洞）。 */
              title={
                selected.base_url_env_var
                  ? `端点由后端按注册表给出，这里不接收输入；要改请设环境变量 ${selected.base_url_env_var} 再重启`
                  : '端点由后端按注册表给出，这里不接收输入；要改请设 .env 的 LLM_BASE_URL 再重启'
              }
            />
          </div>

          <div className="ms-key-actions">
            <Tooltip title="只在这一次进程里生效，不写任何文件">
              <span>
                {/* 从 primary 降成默认（白底描边）那一档：这一栏下面还有
                    「撤回，回落 .env」，两颗里给任何一颗上主色都会读成"这才是主操作"，
                    而这一屏真正的主操作是**提交任务**（在遮罩外面那颗按钮上）。
                    （「校验」2026-09-29 搬进了输入框右端，这里不再占一个按钮位。） */}
                <Button
                  size="small"
                  onClick={commit}
                  loading={applyKey.isPending}
                  disabled={!canSend}
                >
                  应用到本次运行
                </Button>
              </span>
            </Tooltip>
            {selected.key_source === 'runtime' ? (
              <Button
                size="small"
                onClick={revoke}
                loading={applyKey.isPending}
                /* ⚠️ 撤回不带着手上的草稿：那是另一件事（换成新的那把），
                   一键两用会出"以为撤了其实换了"的错。 */
                title={`撤掉面板填的那把，回落到 ${selected.own_key_env_var ?? selected.key_env_var}`}
              >
                撤回，回落 .env
              </Button>
            ) : null}
          </div>

          {/* ⚠️ 这行"已暂存"的说明**必须排在按钮下面**，不能夹在输入框与按钮之间。
             探针逼出来的真缺陷：它只在 blur 那一刻出现，放在上面的话
             mousedown → blur → 插入一整行 ⇒ 按钮在 mouseup 之前往下跳一行 ⇒
             这一下点击落在空处，用户要点第二下才有反应（现象就叫"点了校验没反应"）。
             校验结果那两行同理排在下面：任何"做过一步才出现"的文字都不许顶到控件上面。 */}
          {shown === '' && draft !== '' ? (
            <p className="ms-key-hold">
              输入框已经清空（这是刻意的：屏幕上不留），刚才那把仍在本页内存里待提交 ——
              「校验」与「应用到本次运行」用的是它，重新输入会替换它。
            </p>
          ) : null}

          {probeView ? (
            <p
              className={`ms-key-result ${probeView.ok ? 'ms-key-result--ok' : 'ms-key-result--bad'}`}
              role="status"
              data-probed-url={probeView.base_url}
            >
              {probeView.ok ? '校验通过：' : '校验没通过：'}
              {probeView.detail}
              <span className="ms-key-meta">
                {/* ⚠️ 端点只在**对不上**的时候说：一致时再印一遍就是"同屏两份同数"
                    （上面那格只读框已经写着它了）。
                    而对不上那一刻正是这条链最贵的读数 —— 「面板说会打智谱、请求其实打着别处」
                    是方案 T-1 那一类，这里靠响应的 ``base_url`` 现场点名，不靠前端推断。 */}
                {probeView.base_url !== selected.base_url
                  ? `实际打在 ${probeView.base_url} · 与上面那格不一致 `
                  : ''}
                {probeView.latency_ms} ms · 超时上限 {probeView.timeout_s} 秒
              </span>
            </p>
          ) : null}
          {probe.isError ? (
            <p className="ms-key-result ms-key-result--bad" role="alert">
              {describeFetchError(probe.error).message || '校验请求未能发出'}
            </p>
          ) : null}
        </>
      )}

      {/* 2026-09-29：原来这里有一整块「一行一家」的状态清单
          （``● DeepSeek（已配置） · 来源：环境变量 LLM_API_KEY · 3 个候选 · 分高峰/低谷`` ×3）。
          整块删掉 —— 那三行读的**全部**是「供应商」那一格已经在说的事：
          状态（已配置 / 未配置）与来路（环境变量哪一把）都写在那一格的选项串里，
          而选中的那家**就显示在框里**（Select 显示的就是它的 label）。
          留着就是同一屏两份同数，还占掉半屏。
          ⚠️ 因此"这家现在发不发得出请求""用的是哪一把"这两件事的读点
             **只剩那一格** —— 探针 AE 那几条也跟着改读 ``.ms-key-select`` 的显示值。 */}
    </div>
  );
}


/** 右上角齿轮那份「模型设置」，以及「设置」中心里的「模型」项，**共用这一个组件**。
 *
 * :param:`embedded` 只改两件事，不改任何行为：
 * ① 不印自己那行标题（宿主那一屏已经有分组标题了，同屏两份「模型设置」是装饰不是信息）；
 * ② 不画「回落到 .env」那颗 —— 设置中心把它放进了**底部固定操作栏**，
 *    同一屏两颗做同一件事的按钮，正是这一轮清单反掉的形状。齿轮那份照旧有。
 * :param:`idPrefix` 见 :func:`KeySection` 上面那段：两个宿主同时在场时 id 不许撞。
 * :param:`onDirtyChange` 把"这一屏有没有改过东西"报给宿主（底栏那枚 dirty 小圆点）。
 *    两个档位的草稿住在**这一层**，而小圆点住在 ``RunConfigPanel`` 的footer里 ——
 *    不报出去的话，"改了下拉框但小圆点还是灰的"就是必然的。
 * :param:`resetSignal` 递增 = 把这一屏清回出厂态（底栏那颗「恢复默认配置」）。
 *    只靠服务端状态回流不够：``useEffect`` 里那条"用户改过就不覆盖"的规矩
 *    （防止打字打到一半被替换）会让两个输入框停在旧值上。
 */
export default function ModelSettingsPanel({
  onClosed,
  embedded = false,
  onDirtyChange,
  resetSignal = 0,
}: {
  onClosed?: () => void;
  embedded?: boolean;
  onDirtyChange?: (dirty: boolean) => void;
  resetSignal?: number;
}) {
  const idPrefix = embedded ? 'sc-' : '';
  const registry = useModelRegistry();
  const { message } = App.useApp();
  const [large, setLarge] = useState('');
  const [small, setSmall] = useState('');
  /** 这个档位的输入框此刻**正在被打字**吗（决定下拉要不要过滤，见 filterOption）。 */
  const [typing, setTyping] = useState<Record<'large' | 'small', boolean>>({
    large: false,
    small: false,
  });

  const apply = useModelOverrideMutation();
  const revert = useModelOverrideReset();

  /** 向量模型那一行读知识库总览 —— 值不在 ``/models`` 里，前端不自己写一份。 */
  const knowledge = useQuery({ queryKey: ['knowledge-overview'], queryFn: fetchKnowledgeOverview });

  const catalog = registry?.catalog;
  const providers = registry?.providers;
  const override = registry?.override;

  /* 表单初值跟着**服务端状态**走：胶囊在别处被刷新、或应用成功后，这里不能停在旧值上。
     只在"用户没在编辑"时同步（否则打字打到一半会被替换）。 */
  const serverLarge = currentTier(registry, 'large');
  const serverSmall = currentTier(registry, 'small');
  const [dirty, setDirty] = useState(false);
  /** Key 那一栏手上有没有"填了没提交"的那把（由 :func:`KeySection` 报上来）。 */
  const [keyDirty, setKeyDirty] = useState(false);
  useEffect(() => {
    if (dirty) return;
    setLarge(serverLarge);
    setSmall(serverSmall);
  }, [serverLarge, serverSmall, dirty]);

  /* 「恢复默认配置」⇒ 先把"用户改过"这个锁解开，再让上面那条同步把输入框拉回服务端值。
     顺序不能反：直接 ``setLarge(serverLarge)`` 会用到**旧的那一份** serverLarge
     （覆盖还在生效时的值），界面于是显示"恢复了"而实际还停在覆盖上。 */
  useEffect(() => {
    if (!resetSignal) return;
    setDirty(false);
    setKeyDirty(false);
  }, [resetSignal]);

  /* 两个档位 / Key 任一有未提交的改动 ⇒ 报给宿主（底栏那枚小圆点）。 */
  useEffect(() => {
    onDirtyChange?.(dirty || keyDirty);
  }, [dirty, keyDirty, onDirtyChange]);

  const grouped = useMemo(() => {
    const byProvider = new Map<string, ModelCatalogEntry[]>();
    for (const entry of catalog ?? []) {
      const list = byProvider.get(entry.provider) ?? [];
      list.push(entry);
      byProvider.set(entry.provider, list);
    }
    return [...byProvider.entries()].map(([provider, entries]) => ({
      label: entries[0]?.provider_display ?? provider,
      options: entries.map((entry) => ({
        value: entry.id,
        label: <OptionLines entry={entry} />,
        /* ⚠️ 没配 Key 的行**照样可选**（只标注不挡）：判定权在后端，它才知道环境变量。
           这里提前 disable 一道就是第二份规则，规则一改两边就会有一天不一致；
           而真被拒时服务端那句"这几家还没有配 API Key：…"比这里能编出来的话更准。 */
      })),
    }));
  }, [catalog]);

  if (!catalog || catalog.length === 0) {
    return (
      <div className="model-settings model-settings--empty" role="status">
        {embedded ? null : <p className="model-settings-title">模型设置</p>}
        <p className="model-settings-note">
          这一趟没读到候选清单（``GET /models`` 里没有 catalog 字段）。
          后端多半是这次改动之前起的进程 —— 新端点要重启后端才在，
          重启之前这里不给下拉，也不假装能换。
        </p>
        {registry?.items?.length ? (
          <p className="model-settings-note">
            现在实际在用：{registry.items.map((item) => `${item.id}（${TIER_LABEL[item.tier]}）`).join('、')}
          </p>
        ) : null}
      </div>
    );
  }

  const unchanged = large === serverLarge && small === serverSmall;
  const missing = !large.trim() || !small.trim();
  /* Key 那一栏默认落在**决策模式当前那一家**：用户打开面板多半就是给正在用的这家配 Key。
     这是个默认值不是判断 —— 真正的"哪家缺 Key、缺的是哪个环境变量"全由响应说。 */
  const defaultKeyProvider =
    catalog.find((entry) => entry.id === serverLarge.trim().toLowerCase())?.provider ?? '';

  const submit = () => {
    apply.mutate(
      { model_large: large.trim(), model_small: small.trim() },
      {
        onSuccess: (ack) => {
          setDirty(false);
          void message.success(ack.message);
        },
        onError: (err) => {
          // 服务端原话优先（它才知道缺哪家的 Key）；这条纪律与 F-1 那一轮相同
          const described = describeFetchError(err);
          void message.error(described.message || '换模型失败');
        },
      },
    );
  };

  return (
    <div className="model-settings">
      {embedded ? null : <p className="model-settings-title">模型设置</p>}

      {/* 2026-09-29：原来开头那一句「改动只影响之后新建的任务…后端重启后回落到 .env」
          整段删掉。它讲的**三件事**（作用范围 / 在途任务怎么记账 / 重启回落）里，
          前两件在这一屏没有任何对应控件（用户改不了"在途任务怎么记账"），
          第三件在 Key 那一栏的占位符里已经写着 —— 同屏两份同样的话。
          而"改动对哪些任务生效"这件事在**提交任务那一刻**才存在，
          摆在一个还没改任何东西的面板顶上，读到的是一句与当前动作无关的话。 */}

      {/* 分区靠**标题加粗 + 24px 留白**，不再给横向分割线（2026-09-29）：
          这一屏从上到下是"模型配置 → API 配置 → 向量模型"三段，段与段之间是**并列**
          而不是"上一节的续"，发丝线读出来的却是"分隔线下面归另一套规则"。 */}
      <p className="ms-section-title">模型配置</p>
      {/* 「角色绑定」那一行小字：整块五行表的替代（那五行永远不可能不一致，
          见 :const:`ROLE_BINDING` 上面的注释）。12px 灰字、无交互，
          职责明细交给末尾那颗 ⓘ —— 摆在这里而不是藏进浮层，
          是因为"两档分别管谁"是这一屏**必须一眼读到**的事。 */}
      <p className="ms-rolebind">
        <span className="ms-rolebind-text">{ROLE_BINDING}</span>
        <Tooltip
          title={
            <span className="ms-rolebind-tip">
              {ROLE_DUTY.map(([role, duty]) => (
                <span key={role} className="ms-rolebind-row">
                  {role}：{duty}
                </span>
              ))}
            </span>
          }
        >
          <span className="ms-info ms-rolebind-info" tabIndex={0} aria-label="五个角色各负责什么">
            <InfoCircleOutlined />
          </span>
        </Tooltip>
      </p>

      {override?.source === 'override' ? (
        <p className="model-settings-badge">
          本进程已覆盖（版本 {override.version}）
          {override.applied_at ? ` · ${override.applied_at.slice(0, 16).replace('T', ' ')} 生效` : ''}
          {override.previous_large ? ` · 原为 ${override.previous_large}` : ''}
        </p>
      ) : null}

      {(['large', 'small'] as const).map((tier) => {
        const value = tier === 'large' ? large : small;
        const setValue = tier === 'large' ? setLarge : setSmall;
        return (
          <div className="model-settings-row" key={tier}>
            {/* 2026-09-29：标签下面那行 hint（"planner / reviewer / judge 用它"）删掉了 ——
                它与上面那行「角色绑定」是**同一句话的两种写法**，同屏两份同数。
                顺带把这两行从 55px 压到 24px：这一格要一屏放得下（验收第 7 条），
                而省下来的地方正是"信息量为零的那一行"占的。 */}
            <label className="model-settings-label" htmlFor={`${idPrefix}model-${tier}`}>
              {TIER_LABEL[tier]}
            </label>
            <AutoComplete
              id={`${idPrefix}model-${tier}`}
              className="model-settings-input"
              value={value}
              options={grouped}
              /* 「模型切换要有下拉标识」这一条落在这儿（补充约束 4 的那颗出口）：
                 这两行就是本面板**唯一真能改模型的地方**，所以箭头加在这里。
                 ⚠️ 用 ``suffixIcon`` 而不是换成 ``Select``：后者会把"自由填模型 id"
                 那一条（方案 L-3）弄丢 —— 标识要加，能力不能减。
                 这一档切换是**进程级**的，放进那张"本次任务"的面板会让人以为换的只是这个任务。
                 （2026-09-29：设置中心里「角色模型映射」那五行表已删 —— 两档分别管谁
                   由本面板顶部那行「角色绑定」小字说清，不再占半屏。） */
              suffixIcon={<DownOutlined className="ms-caret" aria-hidden="true" />}
              /* ---------- 弹层那一屏的形状（2026-09-27）：宽、折行、两行一项、限高 ----------
                 三条各管一件事，都量过（AD-69 / AD-69b，负面对照 NC-69）：
                 · ``popupMatchSelectWidth={false}`` —— 默认值让弹层跟输入框同宽，
                   而输入框这一档被卡片限到 280px ⇒ 弹层也只有 280，长话必被截。
                   ⚠️ NC-69 判的就是这条：拿掉它，读回来 w=280 而 wantW=600，只红 AD-69 一条。
                 · 弹层的宽度写在 index.css 的 ``.ms-model-pop`` 上而不是这里 ——
                   "600 与 90vw 谁小听谁的"这种值本来就归媒体查询管（≤768 那一档另退一档），
                   内联 style 做不到；宽度也**不跟内容长**，否则一换候选清单弹层就换一次宽，
                   鼠标移过去的路上会点错行。
                 · ``virtual={false}`` —— 虚拟列表按固定行高排，而这里的行会折行。
                   ⚠️ 这一条在当前组合下其实是**自动成立**的：rc-select 里
                   ``realVirtual = virtual !== false && dropdownMatchSelectWidth !== false``，
                   只要弹层不跟输入框同宽，虚拟列表就自己关了（NC-69 顺带量到：把这一行删掉，
                   DOM 里的候选条数不变）。写出来不是冗余声明，是让下一位知道
                   "为什么这里看得见全部候选"，以及哪天把 ``popupMatchSelectWidth`` 改回
                   true 时，折行的行高是谁在兜。 */
              popupMatchSelectWidth={false}
              listHeight={360}
              virtual={false}
              classNames={{ popup: { root: 'ms-model-pop' } }}
              onChange={(next) => {
                setDirty(true);
                setValue(next);
              }}
              placeholder="选一个，或直接填模型 id"
              /* ⚠️ "只在真正打字时才过滤"这一条是探针 AC-1 逼出来的：
                 AutoComplete 默认拿**输入框当前值**过滤，而当前值就是已生效的那个模型名 ⇒
                 一打开下拉只剩它自己一条，看着像"候选清单只有一家"。
                 用户点开这个控件是为了看全部选项，不是看现在这一个。
                 搜索串按 ``value`` 回查 catalog 再交给 :func:`optionSearchText` ——
                 ``option.label`` 现在是 ReactNode，拿它当搜索串会静默筛光所有候选。 */
              filterOption={(input, option) => {
                if (!typing[tier]) return true;
                /* 按分组结构传参时 AntD 的 filterOption 收到的是**叶子项**，
                   而 TS 的分组类型把参数标成了组对象 ⇒ 这里做一次显式收窄。 */
                const leaf = option as unknown as { value?: string };
                const needle = input.trim().toLowerCase();
                if (!needle) return true;
                const hit = (catalog ?? []).find((entry) => entry.id === leaf.value);
                /* 填进来的 id 不在候选里 ⇒ 至少还能按自己打的字回显，别一律筛掉。 */
                if (hit) return optionSearchText(hit).includes(needle);
                return String(leaf.value ?? '').toLowerCase().includes(needle);
              }}
              onSearch={() => setTyping((prev) => ({ ...prev, [tier]: true }))}
              onSelect={() => setTyping((prev) => ({ ...prev, [tier]: false }))}
              onBlur={() => setTyping((prev) => ({ ...prev, [tier]: false }))}
              /* 允许自由填（方案 L-3 拍的那一条）。
                 2026-09-29：下面那整段单价说明（口径 / 折算汇率 / 官网核对日期 / 来源链接）
                 删掉 —— 它是**报价的出处**，不是"选哪个"需要的信息：
                 真要核对的人在下拉候选第二行已经看到阶梯价，而"这个价怎么算的"
                 该去成本归因那一屏看（那里按每一次调用记账，才是这件事的读点）。
                 摆在这里的结果是两档各多出两行长句，把"选模型"挤成了次要动作。 */
            />
          </div>
        );
      })}

      {apply.isError ? (
        <p className="model-settings-error" role="alert">
          {describeFetchError(apply.error).message || '换模型失败'}
        </p>
      ) : null}

      <div className="model-settings-actions">
        <Tooltip title={unchanged ? '与当前生效的两个档位相同' : ''}>
          <span>
            <Button
              type="primary"
              size="small"
              onClick={submit}
              loading={apply.isPending}
              disabled={unchanged || missing}
            >
              应用
            </Button>
          </span>
        </Tooltip>
        {/* 内嵌态不给这颗：「设置」中心把它挪到了**底部固定操作栏**（那一栏在三个分组之间
            常驻，回落到 .env 这件事本来就不属于"模型"这一组）。齿轮那份照旧。 */}
        {embedded ? null : (
          <Button
            size="small"
            onClick={() =>
              revert.mutate(undefined, {
                onSuccess: () => {
                  setDirty(false);
                  onClosed?.();
                },
              })
            }
            loading={revert.isPending}
            disabled={override?.source !== 'override'}
          >
            回落到 .env
          </Button>
        )}
      </div>

      <KeySection
        providers={providers ?? []}
        defaultProvider={defaultKeyProvider}
        idPrefix={idPrefix}
        onDirtyChange={setKeyDirty}
        resetSignal={resetSignal}
      />

      {/* 原来这一栏的标题写着"（这里不改）"、正文又用两句话解释为什么不改 ——
          同一个意思说了两遍。现在标题只报名字，"为什么不改"交给 ⓘ，正文一行读数。
          ⚠️ 读不到向量模型名时**不许印成"当前使用：（只读）"**：那是一句假话。
          这一行此前**一条判据都没有**（向量模型那半屏全站零覆盖），本轮补了 AD-70 钉两态。
          2026-09-29：正文里那个「（只读）」换成**模型名右侧一枚锁图标** ——
          同样是"改不了"，一枚图标比四个括号字少占半行，而读屏那边靠 ``aria-label``
          拿到的是一句完整的话（"只读，不提供修改入口"），不是"括号只读括号"。 */}
      <p className="ms-section-title">向量模型</p>
      <p className="model-settings-note">
        {knowledge.data?.embedding_model ? (
          <>
            <>
              当前使用：
              {/* 模型 id 走等宽：这一屏的既有口径（旧角色表里的 .rcp-model-id 就是等宽胶囊），
                  那张表删掉之后等宽的读点搬到这一枚上（AD-44 读的就是 .ms-embed-id）。 */}
              <code className="ms-embed-id">{knowledge.data.embedding_model}</code>
            </>
            <Tooltip title="只读：更换向量模型会导致全库索引指纹失配，检索报 409，需要重建索引，这里不提供修改入口。">
              <span
                className="ms-embed-lock"
                tabIndex={0}
                role="img"
                aria-label="只读，不提供修改入口"
              >
                <LockOutlined />
              </span>
            </Tooltip>
          </>
        ) : (
          '这一趟没读到向量模型名（GET /knowledge/overview 没给 embedding_model）'
        )}
      </p>
    </div>
  );
}
