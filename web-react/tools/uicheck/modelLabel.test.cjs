/* modelChipText / modelTooltipLines 的断言集：
   npx esbuild src/utils/modelLabel.ts --bundle --format=cjs --outfile=tools/uicheck/modelLabel.cjs
   node tools/uicheck/modelLabel.test.cjs

   ⚠️ 下面三份 registry payload **不是手编的**：是 2026-09-24 真跑 `GET /models` 抄下来的
   （一份经本机 8001 的活服务、两份经 TestClient 起完整 app 后改 settings），
   与 tools/uicheck/mocks.cjs 里的三份同源。复现：

     python -c "import json;from fastapi.testclient import TestClient;from api.main import app; \
       from api.routes import models as m;from config import Settings; \
       m.get_settings=lambda: Settings(_env_file=None, llm_model_large='deepseek-v4-pro'); \
       print(json.dumps(TestClient(app).get('/models').json(), ensure_ascii=False))"

   这里守的是三条措辞纪律，其中第 2、3 条都是「数字对、话说错了」那一类：
   兜底价不许叫官方价；两档不同不许只报一个大档。 */
const { modelChipText, modelTooltipLines } = require('./modelLabel.cjs');

let pass = 0;
const fails = [];
function eq(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (ok) pass += 1;
  else fails.push(`${name}\n   got  ${JSON.stringify(got)}\n   want ${JSON.stringify(want)}`);
}
function ok(name, cond, got) {
  if (cond) pass += 1;
  else fails.push(`${name}\n   got  ${JSON.stringify(got)}`);
}

/** 本机 .env 的真实形态：两档都是 deepseek-flash ⇒ 后端合并成一条
 *  （role_map 在这里与 mocks.cjs 保持同源，但措辞层**刻意不读**它：
 ``items[].roles`` 已是同一事实的另一面，同屏两份只会多一处能说过话的地方） */
const SINGLE = {
  items: [
    {
      id: 'deepseek-flash',
      provider: 'deepseek',
      tier: 'large',
      roles: ['executor', 'extract', 'judge', 'planner', 'reviewer'],
      price_in_per_million_cny: 2.13,
      price_out_per_million_cny: 8.52,
      price_source: 'official_table',
      configured: true,
    },
  ],
  total: 1,
  role_map: {
    executor: 'deepseek-flash',
    extract: 'deepseek-flash',
    judge: 'deepseek-flash',
    planner: 'deepseek-flash',
    reviewer: 'deepseek-flash',
  },
  default_model: 'deepseek-flash',
  pricing_basis: 'DeepSeek 官方高峰价（美元）按固定汇率折算的人民币；低谷时段再乘 off_peak_multiplier',
  off_peak_multiplier: 0.5,
};

const TWO_TIERS = {
  items: [
    {
      id: 'deepseek-v4-pro',
      provider: 'deepseek',
      tier: 'large',
      roles: ['judge', 'planner', 'reviewer'],
      price_in_per_million_cny: 9.37,
      price_out_per_million_cny: 28.12,
      price_source: 'official_table',
      configured: true,
    },
    {
      id: 'deepseek-flash',
      provider: 'deepseek',
      tier: 'small',
      roles: ['executor', 'extract'],
      price_in_per_million_cny: 2.13,
      price_out_per_million_cny: 8.52,
      price_source: 'official_table',
      configured: true,
    },
  ],
  total: 2,
  default_model: 'deepseek-v4-pro',
  pricing_basis: SINGLE.pricing_basis,
  off_peak_multiplier: 0.5,
};

/** 强模型不在单价表里 ⇒ 兜底默认值本身就等于 flash 的表价，于是**两行数字一模一样**
 *  （2.13 / 8.52）、来路不同 —— 这正是只看数字看不出问题的形态，所以措辞必须分开。
 *  与上面 TestClient 那次真跑的输出一致。 */
const FALLBACK = {
  ...TWO_TIERS,
  items: [
    {
      ...TWO_TIERS.items[0],
      id: '某没配过价的模型',
      price_in_per_million_cny: 2.13,
      price_out_per_million_cny: 8.52,
      price_source: 'settings_fallback',
    },
    TWO_TIERS.items[1],
  ],
  default_model: '某没配过价的模型',
};

/* ---------- 规则 1：拉不到就整条不显示（宁少一行，不造一份清单） ---------- */
eq('null（请求失败）⇒ 空串', modelChipText(null), '');
eq('空清单 ⇒ 空串', modelChipText({ ...SINGLE, items: [], total: 0 }), '');
eq('null ⇒ 无明细', modelTooltipLines(null), []);
eq('空清单 ⇒ 无明细', modelTooltipLines({ ...SINGLE, items: [], total: 0 }), []);

/* ---------- 胶囊文案 ---------- */
eq('两档同一模型：不带 +', modelChipText(SINGLE), '模型 deepseek-flash');
eq(
  '两档不同：必须两个都露出来（只报大档会让人以为全程用它）',
  modelChipText(TWO_TIERS),
  '模型 deepseek-v4-pro +deepseek-flash',
);

/* ---------- 合并成一条时不许说「强模型」 ---------- */
const singleLines = modelTooltipLines(SINGLE);
eq(
  '两档同一 ⇒ 前缀换成「两档同一个模型」，五个角色都在这一行',
  singleLines[0],
  '两档同一个模型 deepseek-flash｜执行/抽取工具/裁判/规划/评审｜¥2.13 进 / ¥8.52 出 每 100 万 token · 表内价',
);
ok(
  '合并那行不出现「强模型 / 快模型」：写「强模型」会让人以为还有个快模型被藏起来了',
  !/强模型|快模型/.test(singleLines[0]),
  singleLines[0],
);

/* ---------- 明细：角色译名、单价两位、来路分开 ---------- */
const twoLines = modelTooltipLines(TWO_TIERS);
eq('两档 ⇒ 两条模型 + 两条说明', twoLines.length, 4);
eq(
  '强模型那行的原样措辞',
  twoLines[0],
  '强模型 deepseek-v4-pro｜裁判/规划/评审｜¥9.37 进 / ¥28.12 出 每 100 万 token · 表内价',
);
eq(
  '快模型那行的原样措辞',
  twoLines[1],
  '快模型 deepseek-flash｜执行/抽取工具｜¥2.13 进 / ¥8.52 出 每 100 万 token · 表内价',
);
ok('低谷系数照抄服务端的 0.5', twoLines[2].includes('×0.5'), twoLines[2]);
ok('峰谷口径用服务端原话，前端不另写', twoLines[2].includes(SINGLE.pricing_basis), twoLines[2]);
ok(
  '末行说清「在哪改 + 改了影响什么 + 会不会一直有效」',
  twoLines[3].includes('模型设置') &&
    twoLines[3].includes('之后新建的任务') &&
    twoLines[3].includes('回落到 .env'),
  twoLines[3],
);
/* 2026-09-26 之前这一行写的是「不在页面里切换」—— 齿轮上线后它就成假话了。
   留这条负向断言是因为：措辞最容易留下的正是这种"前提已经变了、句子还在"的谎。 */
ok('末行不许再说「不在页面里切换」', !twoLines[3].includes('不在页面里切换'), twoLines[3]);

/* ---------- 换供应商之后：不分峰谷的家不许被套上低谷说明 ---------- */
const GLM = {
  ...SINGLE,
  items: [
    {
      id: 'glm-4.6',
      provider: 'zhipu',
      tier: 'large',
      roles: ['planner', 'reviewer', 'judge'],
      price_in_per_million_cny: 1,
      price_out_per_million_cny: 3,
      price_source: 'official_table',
      configured: true,
      /* ⚠️ 桩值刻意与后端真值同形：分档 + 不分峰谷（2026-09-26 官网核对）。 */
      tiered: true,
      peak_off_peak: false,
    },
  ],
  total: 1,
};
const glmLines = modelTooltipLines(GLM);
ok('不分峰谷 ⇒ 不印「低谷时段系数」', !glmLines[1].includes('低谷时段系数'), glmLines[1]);
ok('不分峰谷 ⇒ 明说这家不分', glmLines[1].includes('这家不分高峰 / 低谷'), glmLines[1]);
ok(
  '阶梯模型的报价必须标成下界（否则长上下文被系统性低估而看起来一切正常）',
  glmLines[0].includes('最低档') && glmLines[0].includes('跳档'),
  glmLines[0],
);
const legacyPeakStub = { ...GLM, items: [{ ...GLM.items[0], peak_off_peak: undefined }] };
ok(
  '老后端没给 peak_off_peak ⇒ 按老语义仍印低谷系数（不因此少一行信息）',
  modelTooltipLines(legacyPeakStub)[1].includes('低谷时段系数'),
  modelTooltipLines(legacyPeakStub)[1],
);

/* ---------- 规则 2：兜底价不许叫官方价 ---------- */
const fb = modelTooltipLines(FALLBACK);
const fbLarge = fb[0];
const fbSmall = fb[1];
ok('表外那行标了「兜底价」', fbLarge.includes('· 兜底价'), fbLarge);
ok('表内那行仍标「表内价」', fbSmall.includes('· 表内价'), fbSmall);
ok(
  '两行数字一模一样（2.13/8.52）却必须不同措辞 —— 只看数字看不出谁是被兜底的',
  fbLarge.includes('¥2.13 进 / ¥8.52 出') && fbSmall.includes('¥2.13 进 / ¥8.52 出'),
  [fbLarge, fbSmall],
);
ok('兜底那行不许出现「表内价」', !fbLarge.includes('表内价'), fbLarge);

/* ---------- 角色译名：认不得的角色原样透出，不猜、不丢 ---------- */
const withUnknown = {
  ...SINGLE,
  items: [{ ...SINGLE.items[0], roles: ['planner', 'brand_new_role'] }],
};
ok('未收录角色保留英文 id', modelTooltipLines(withUnknown)[0].includes('规划/brand_new_role'), modelTooltipLines(withUnknown)[0]);

/* ---------- 单价小数位：两位（全站金额口径一致） ---------- */
const odd = {
  ...SINGLE,
  items: [{ ...SINGLE.items[0], price_in_per_million_cny: 2.13456, price_out_per_million_cny: 8 }],
};
ok('四舍五入到两位', modelTooltipLines(odd)[0].includes('¥2.13 进 / ¥8.00 出'), modelTooltipLines(odd)[0]);

console.log(`modelLabel: ${pass} 通过 / ${pass + fails.length} 断言`);
if (fails.length) {
  console.error(fails.map((f) => `  ✗ ${f}`).join('\n'));
  process.exit(1);
}
