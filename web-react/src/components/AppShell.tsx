import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Drawer, Popover, Tooltip } from 'antd';
import {
  AppstoreOutlined,
  BarChartOutlined,
  CopyOutlined,
  FileTextOutlined,
  NodeIndexOutlined,
  ReloadOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';

import { API_LABEL, USE_MOCK, fetchHealth } from '../api/client';
import type { HealthView } from '../api/client';
import { useCopy } from '../hooks/useCopy';
import { useIsMid, useIsNarrow } from '../hooks/useMediaQuery';
import { useRefresh } from '../hooks/useRefresh';
import { useTasklist } from '../hooks/useTasklist';
import { useThemeMode } from '../hooks/useThemeMode';
import { fmtDuration } from '../utils/format';

export interface NavItem {
  key: string;
  label: string;
  /** 底部标签栏用的短标签（窄屏只有 ~1/3 屏宽）。 */
  short: string;
  group: string;
  icon: ReactNode;
  desc: string;
}

/** 导航单一事实来源：图标栏、面包屑、底部标签栏、路由标题都读它。 */
export const NAV_ITEMS: NavItem[] = [
  {
    key: '/tasks',
    label: '任务与日志',
    short: '任务',
    group: '工作台',
    icon: <AppstoreOutlined />,
    desc: '提交任务 · 实时日志 · 结果',
  },
  {
    key: '/trace',
    label: '轨迹回放',
    short: '轨迹',
    group: '分析',
    icon: <NodeIndexOutlined />,
    desc: '逐步回看编排过程',
  },
  {
    key: '/eval',
    label: '评测与消融',
    short: '评测',
    group: '分析',
    icon: <BarChartOutlined />,
    desc: '检索指标与消融对比',
  },
  {
    key: '/knowledge',
    label: '知识库',
    short: '知识库',
    group: '工作台',
    icon: <FileTextOutlined />,
    desc: '上传文档 · 索引进度 · 删除与重试',
  },
];

/** 线性图标统一走 .stroke-icon：线宽 / 端点 / 圆角由 --icon-stroke 单点控制，
 *  与参考包的线宽 1.4 对齐 —— AntD 的填充图标改不了线宽，所以自绘图标必须自己守住规范。
 */
function SunIcon() {
  return (
    <svg className="stroke-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg className="stroke-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden>
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
    </svg>
  );
}

/** 收起 / 展开任务列表：一栏 + 一条分隔线的隐喻。 */
function PanelIcon() {
  return (
    <svg className="stroke-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M9.5 4v16" />
    </svg>
  );
}

/** 品牌图形：三节点协作网络（Planner ◆ / Executor ▶ / Reviewer ✔）。
 *
 * 取自参考包的 BrandMark：线宽 1.4、圆角端点、四个节点用不同亮度的圆形区分角色。
 * 之所以用「网络」而不是字母标：这个控制台的主语本来就是多 Agent 协作，
 * 图形能直接说清它是干什么的，字母标（原来的 "a1"）做不到。
 */
function BrandMark() {
  return (
    <svg width="21" height="21" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        className="stroke-icon"
        d="M9 4.5 4.5 15M15 4.5 19.5 15M6.5 19.5h11"
        stroke="rgba(255,255,255,.55)"
      />
      <circle cx="9" cy="4.5" r="2.4" fill="#fff" />
      <circle cx="4.5" cy="15" r="2.4" fill="#c7d2fe" />
      <circle cx="19.5" cy="15" r="2.4" fill="#e9d5ff" />
      <circle cx="12" cy="19.5" r="2.4" fill="#a5b4fc" />
    </svg>
  );
}

/* ------------------------------------------------------------------ *
 * 顶部状态：数据源 + 健康度
 * ------------------------------------------------------------------ */

type HealthKind = 'loading' | 'ok' | 'degraded' | 'down' | 'mock';

interface HealthPill {
  kind: HealthKind;
  label: string;
}

const DOT_CLASS: Record<HealthKind, string> = {
  loading: 'dot',
  ok: 'dot dot--live',
  degraded: 'dot dot--warn',
  down: 'dot dot--off',
  mock: 'dot dot--warn',
};

const CHECK_LABEL: Record<string, string> = {
  api: 'API',
  database: '数据库',
  redis: '缓存',
  llm: 'LLM',
  queue: '队列',
  rag: '知识库',
};

/** 各项异常时可一键复制的修复动作。
 *
 *  为什么需要它：后端 /health 已经返回了具体原因（check.detail），
 *  比如「sqlite-vec 未安装，无法使用 sqlite-vec 后端」，但用户看完仍然不知道下一步干嘛。
 *  给一条能直接粘到终端的命令，才算把「排查」这件事闭环。
 */
const FIX_HINT: Record<string, string> = {
  rag: 'pip install sqlite-vec',
  redis: 'redis-server',
  llm: '# 在后端 .env 中配置 LLM_API_KEY 后重启',
  database: '# 检查 data/ 目录读写权限后重启后端',
  queue: '# 重启后端以重建任务队列',
  api: '# 重启后端：python scripts/start_api.py',
};

function useHealth(token: number): { pill: HealthPill; detail: ReactNode } {
  const [view, setView] = useState<HealthView | null>(null);
  const [down, setDown] = useState(false);
  const [loading, setLoading] = useState(true);
  const copy = useCopy();

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      /* 后台标签不发探测（省一个必然被浏览器节流过的 RTT）。这里**故意**留在 try/finally
         外面早退：没测过就不能谎报结果 —— 既不能写成「后端未连接」，也不许把 loading 抹掉，
         否则徽标会停在一个说谎的读数上。上一版的病正在这：这一行 return 跑在 finally 之前，
         于是"页面在后台被打开"这条路径上 `loading` 永远是 true，切回来还得等下一个 30 秒
         刻度才动（N4 + B11）。让它动起来的是下面那个 visibilitychange 补拉。 */
      if (typeof document !== 'undefined' && document.hidden) return;
      try {
        const next = await fetchHealth();
        if (!alive) return;
        setView(next);
        setDown(false);
      } catch {
        if (!alive) return;
        setView(null);
        setDown(true);
      } finally {
        if (alive) setLoading(false);
      }
    };
    void tick();
    const id = window.setInterval(() => void tick(), 30_000);
    /* 切回前台立刻补一次，不等下一个 30 秒刻度：用户回到这一屏时读到的该是"现在"的状态，
       而不是一小时前的旧值（后台计时器还会被浏览器压到分钟级）。 */
    const onVisible = () => {
      if (!document.hidden) void tick();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      alive = false;
      window.clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [token]);

  const pill: HealthPill = USE_MOCK
    ? { kind: 'mock', label: 'Mock 数据' }
    : loading
      ? { kind: 'loading', label: '探测中' }
      : down
        ? { kind: 'down', label: '后端未连接' }
        : view?.status === 'healthy'
          ? { kind: 'ok', label: '服务正常' }
          : view?.status === 'degraded'
            ? { kind: 'degraded', label: '降级运行' }
            : { kind: 'down', label: '服务不健康' };

  const detail = USE_MOCK ? (
    <span>前端运行在 Mock 数据源，未连后端</span>
  ) : down ? (
    <span>
      无法访问 <code>{API_LABEL}</code>
      <br />
      确认后端已启动（<code>scripts/start_api.py</code>）
    </span>
  ) : view ? (
    <div className="health-pop">
      <div className="health-pop-head">
        版本 {view.version} · 已运行 {fmtDuration(view.uptime_seconds * 1000)}
      </div>
      {/* 「降级」是后端 status 的直译，第一次看到的人读不出它是好是坏。
          口径写在异常项里，不在胶囊文字上 —— 胶囊只有 8 个字符的位置。 */}
      {view.status === 'degraded' && (
        <p className="health-pop-note">
          降级 = 服务在线、能接任务，但下面标黄的这项能力暂时不可用；受影响的功能会在任务里如实报错。
        </p>
      )}
      {Object.entries(view.checks).map(([key, check]) => (
        <div className={`health-row health-row--${check.status}`} key={key}>
          <span className="health-row-top">
            <span className={`health-dot health-dot--${check.status}`} aria-hidden />
            <span className="health-name">{CHECK_LABEL[key] ?? key}</span>
            <span className="health-state">
              {check.status === 'ok' ? '正常' : check.status === 'degraded' ? '降级' : '异常'}
            </span>
          </span>
          {/* 后端给的具体原因 —— 之前只显示「正常/降级/异常」，把这段最有信息量的话丢了 */}
          {check.detail && <span className="health-detail">{check.detail}</span>}
          {check.status !== 'ok' && FIX_HINT[key] && (
            <button
              type="button"
              className="health-fix"
              onClick={() => void copy(FIX_HINT[key], { okMessage: '命令已复制，粘到终端即可' })}
            >
              <CopyOutlined /> 复制修复命令
            </button>
          )}
        </div>
      ))}
    </div>
  ) : (
    <span>探测中…</span>
  );

  return { pill, detail };
}

/* ------------------------------------------------------------------ *
 * 右上角「模型设置」入口
 * ------------------------------------------------------------------ */

/** 面板本体是**懒加载**的：``AppShell`` 在入口 chunk 里，而 99% 的会话从不打开这个面板。
 *  它要用 ``AutoComplete`` / ``Button`` 等组件，直接 import 会把这些一起拖进入口 ——
 *  ``tools/uicheck/bundle.cjs`` 量的就是这一格（入口 gzip 与占比）。 */
const ModelSettingsPanel = lazy(() => import('./ModelSettings'));

/** 齿轮 + 承载面：宽屏走 Popover，与既有「数据源体检」胶囊同一交互族；
 *  390 窄屏走 Drawer（弹层在这个宽度上会被顶栏截掉半屏，且滚动区域比屏幕还长）。 */
function ModelSettingsEntry({ compact }: { compact: boolean }) {
  const [open, setOpen] = useState(false);
  /* 2026-09-27：这里原来还挂着一个 ``onOpenModelSettings`` 监听 —— 服务对象是
     「运行配置」面板里那颗「去设置」。模型设置现在**内嵌在设置中心的「模型」项里**，
     那颗按钮要跳的地方就在同一屏下面，按钮与事件一起删了。
     留着一个只有接收端、没有发送端的 window 事件，就是 R-13 那个形状
     （"由测试养着的产线死代码"）—— 与其挂着，不如连文件一起摘掉。 */
  const trigger = (
    <button
      type="button"
      className={`icon-btn${open ? ' icon-btn--active' : ''}`}
      aria-label="模型设置"
      aria-haspopup="dialog"
      aria-expanded={open}
      /* ⚠️ 宽屏这一支**不绑 onClick**：Popover 的 trigger="click" 已经会走
         onOpenChange，这里再自己翻一次就是"开→立刻关"，点起来像没反应。
         窄屏那支没有 Popover 包裹，才需要自己把抽屉打开。 */
      onClick={compact ? () => setOpen(true) : undefined}
    >
      <SettingOutlined />
    </button>
  );
  const body = (
    <Suspense fallback={<p className="model-settings-loading">模型设置加载中…</p>}>
      <ModelSettingsPanel onClosed={() => setOpen(false)} />
    </Suspense>
  );
  if (compact) {
    return (
      <>
        {trigger}
        <Drawer
          className="model-settings-drawer"
          title="模型设置"
          placement="bottom"
          height="78%"
          open={open}
          onClose={() => setOpen(false)}
          styles={{ body: { padding: '12px 14px' } }}
        >
          {body}
        </Drawer>
      </>
    );
  }
  return (
    <Popover
      trigger="click"
      placement="bottomRight"
      open={open}
      onOpenChange={setOpen}
      content={body}
      overlayClassName="model-settings-popover"
    >
      {trigger}
    </Popover>
  );
}

/* ------------------------------------------------------------------ *
 * 外壳
 * ------------------------------------------------------------------ */

export default function AppShell({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const isMid = useIsMid();
  const isNarrow = useIsNarrow();
  const { mode, toggle: toggleMode } = useThemeMode();
  const { token, refresh } = useRefresh();
  const { collapsed: listCollapsed, toggle: toggleList } = useTasklist();

  const currentItem = useMemo(
    () => NAV_ITEMS.find((i) => location.pathname.startsWith(i.key)) ?? NAV_ITEMS[0],
    [location.pathname],
  );

  const { pill, detail } = useHealth(token);

  const go = useCallback((key: string) => navigate(key), [navigate]);

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到主内容
      </a>

      {/* 62px 图标栏。四个入口都不放文字：图标 + tooltip + 选中态足够定位，
          「我在哪一页」由顶栏面包屑说。原来这条是 240px 的文字栏，与第二栏任务列表
          并成两条左栏，中窗口下主区被压得整屏换行（重设计清单 P0#1）。
          ⚠️ 这里原先写的是"三页的标签都是四个字" —— 那句本来就不成立（「任务与日志」
          五个字），2026-09-26 加第四页时一起改掉：留一条对不上的口径，比留一条说得粗的
          口径危险得多 —— 下一个人会拿它当依据。 */}
      <aside className="app-rail" aria-label="主导航">
        <span className="rail-logo" aria-hidden>
          <BrandMark />
        </span>

        <nav className="rail-nav">
          {NAV_ITEMS.map((item) => {
            const active = currentItem.key === item.key;
            return (
              <Tooltip
                key={item.key}
                title={`${item.label} · ${item.desc}`}
                placement="right"
                trigger={['hover', 'focus']}
              >
                <button
                  type="button"
                  className={active ? 'rail-btn is-active' : 'rail-btn'}
                  aria-current={active ? 'page' : undefined}
                  aria-label={item.label}
                  onClick={() => go(item.key)}
                >
                  <span aria-hidden>{item.icon}</span>
                </button>
              </Tooltip>
            );
          })}
        </nav>

        <div className="rail-foot">
          {/* 这一栏原来还有一枚主题切换（2026-09-26 挪到顶栏右上角了），连同它下面那条
              .rail-divider 一起删掉 —— 那条线当时分的正是"操作"与"数据源点"。
              现在整条只剩"通没通"这一件事：图标栏不放操作，操作在顶栏。 */}
          {/* 数据源标识压成一颗状态点：文字口径在顶栏的健康胶囊里，这里只回答「通没通」 */}
          <span
            className={USE_MOCK ? 'dot dot--warn' : 'dot dot--live'}
            aria-label={USE_MOCK ? 'Mock 数据源' : `数据源 ${API_LABEL}`}
            title={USE_MOCK ? 'Mock 数据源' : `数据源 ${API_LABEL}`}
          />
        </div>
      </aside>

      <div className="app-workspace">
        <header className="app-topbar">
          {/* ≤1180px 时任务列表本来就是抽屉，这个按钮没有作用对象，不渲染 */}
          {!isMid && (
            <Tooltip
              title={listCollapsed ? '展开任务列表' : '收起任务列表'}
              placement="bottomLeft"
              trigger={['hover', 'focus']}
            >
              <button
                type="button"
                className="icon-btn icon-btn--ghost"
                onClick={toggleList}
                aria-label={listCollapsed ? '展开任务列表' : '收起任务列表'}
                aria-expanded={!listCollapsed}
              >
                <PanelIcon />
              </button>
            </Tooltip>
          )}

          <div className="topbar-crumbs">
            {/* 品牌名只做展示位：包名 / import 路径 / 仓库名 / 路由 / Docker / env 变量名
                都没跟着改（Trinity 是产品名不是模块名）。窄屏下这一格随 .hide-narrow 收起，
                「我在哪一页」由右边那枚 currentItem.label 说，不依赖品牌名。 */}
            <span className="hide-narrow">Trinity</span>
            <span className="topbar-crumb-sep hide-narrow" aria-hidden>
              /
            </span>
            <span className="topbar-crumb-current">{currentItem.label}</span>
          </div>

          <div className="topbar-actions">
            <Popover
              trigger="click"
              placement="bottomRight"
              title="数据源体检"
              content={detail}
              overlayClassName="health-popover"
            >
              <button
                type="button"
                className={`status-pill status-pill--${pill.kind}`}
                aria-label="数据源体检详情"
              >
                <span className={DOT_CLASS[pill.kind]} aria-hidden />
                <span>{pill.label}</span>
                <code className="hide-compact">{API_LABEL}</code>
              </button>
            </Popover>

            {/* 主题切换：2026-09-26 从图标栏底部挪上来。右上角这一排从此是
                通没通（体检胶囊）→ 长什么样（这一枚）→ 用哪个模型（齿轮）→ 刷新，
                次序由 AC-18 钉着（探针读的是 .topbar-actions 直接子元素的 aria-label 序列）。
                ⚠️ 两条 aria-label 的字**一个都别改**：`capture2.cjs` 是按
                role + name 点它的，换措辞等于把那条截图路径悄悄弄断（不报错，只是点不到）。 */}
            <Tooltip
              title={mode === 'dark' ? '切换到浅色主题' : '切换到深色主题'}
              placement="bottomRight"
              trigger={['hover', 'focus']}
            >
              <button
                type="button"
                className="icon-btn topbar-theme-toggle"
                onClick={toggleMode}
                aria-label={mode === 'dark' ? '切换到浅色主题' : '切换到深色主题'}
              >
                {mode === 'dark' ? <SunIcon /> : <MoonIcon />}
              </button>
            </Tooltip>

            <ModelSettingsEntry compact={isNarrow} />

            <Tooltip title="刷新当前页数据" trigger={['hover', 'focus']}>
              <button
                type="button"
                className="icon-btn"
                onClick={refresh}
                aria-label="刷新当前页数据"
              >
                <ReloadOutlined />
              </button>
            </Tooltip>
          </div>
        </header>

        <main className="app-content" id="main-content" tabIndex={-1}>
          {children}
        </main>

        {isNarrow && (
          <nav className="app-tabbar" aria-label="页面切换">
            {NAV_ITEMS.map((item) => {
              const active = currentItem.key === item.key;
              return (
                <button
                  key={item.key}
                  type="button"
                  className={active ? 'tabbar-item is-active' : 'tabbar-item'}
                  aria-current={active ? 'page' : undefined}
                  onClick={() => go(item.key)}
                >
                  <span aria-hidden>{item.icon}</span>
                  <span>{item.short}</span>
                </button>
              );
            })}
          </nav>
        )}
      </div>
    </div>
  );
}
