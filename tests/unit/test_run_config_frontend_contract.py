"""运行配置面板的**源码级**契约审计：界面不许自带一张字段表。

为什么要有这个文件（而不是只靠 AD 趟）：AD 趟在浏览器里比"界面显示的 == 桩给的"，
那要 dev server + 真浏览器才跑得动；而"前端抄了一份后端的措辞/默认值"这件事
**在源码里就能看见**。R-03（知识库白名单）那条先例的核对方式正是
"grep 确认前端搜不到字面量" —— 这条把那个动作落成用例，免得下次靠人记得去 grep。

三条判据各自挡一种复发：

1. **字段名**：后端 ``fields[].label`` 的中文措辞不许出现在界面的**代码行**里
   （注释里出现是历史交代，故意放过 —— 那些注释是在告诉下一个人别再写回去）。
2. **单位与默认值**：``'轮'`` / ``'元'`` / ``?? 3`` 这类字面量不许出现在代码行里。
   ``mock/taskMock.ts`` 整份排除：那是**假后端**，它模拟"没带就用我的默认"是它的职责。
3. **行表覆盖**：后端声明 accepted 的数值键，必须在前端那张行表里 ——
   漏了的话面板会把它列进「后端还给了这些」（AD-41 管那一半），
   但**这一版界面就该有行**，那是本轮 ``review_threshold`` 踩出来的坑：
   后端早就 accepted+enforced，前端没有行 ⇒ "能配"只在后端成立。

⚠️ 前两条**做过负面对照**：把 AD-neg3 那份临时补丁（在 ``NumericRow`` 里塞回一张
``{label, unit}`` 表）打上再跑本文件，``不许出现后端那套字段名`` 与
``不许出现单位后缀字面量`` 两条**当场判红**；撤掉补丁回到全绿。
扫描器本身也量过：一次扫到 8932 行代码行，探针对 ``'未收下'`` 这类带引号的字面量命中 1 处
⇒ 命中为空是"真的没有"，不是"没在扫"。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from api.routes.config import _fields
from api.schemas import RUN_CONFIG_LIMITS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_SRC = PROJECT_ROOT / "web-react" / "src"

#: 参与审计的界面源码（``mock/`` 是假后端，刻意不在此列）
_CODE_GLOBS = ("*.ts", "*.tsx")
_EXCLUDED_DIRS = {"mock"}


def _code_lines() -> list[tuple[Path, int, str]]:
    """返回**去掉注释**之后的源码行：``(文件, 行号, 文本)``。

    只做形状判断，不当解析器用：整行 ``//``、行尾 ``//``、``/* … */``（含 JSDoc 的
    每行 ``*`` 开头）都算注释。代价是多行字符串中间像注释的行会被误删 ——
    本审计找的是一批特定中文串与数字兜底，误删只会**放过**，不会冤枉。
    """
    files = [
        p
        for glob in _CODE_GLOBS
        for p in WEB_SRC.rglob(glob)
        if not (_EXCLUDED_DIRS & set(p.relative_to(WEB_SRC).parts[:-1]))
    ]
    assert files, f"没找到任何源码文件，路径大概是错的：{WEB_SRC}"
    out: list[tuple[Path, int, str]] = []
    for path in files:
        in_block = False
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw.strip()
            if line.startswith("/*") or in_block:
                in_block = not line.endswith("*/")
                continue
            if line.startswith("*") or line.startswith("//"):
                continue
            # 行尾注释切掉，但别把 URL / 字符串里的 "//" 当注释
            cut = re.sub(r"\s+//(?![/]).*$", "", line)
            if cut:
                out.append((path, lineno, cut))
    return out


def _hits(needle: str) -> list[str]:
    return [
        f"{path.relative_to(PROJECT_ROOT)}:{lineno}: {text}"
        for path, lineno, text in _code_lines()
        if needle in text
    ]


# --------------------------------------------------------------------------- #
# 1. 字段名归后端
# --------------------------------------------------------------------------- #
def test_界面代码行里不许出现后端那套字段名() -> None:
    """``fields[].label`` 是界面显示用的名字；抄一份进代码就有第二张字段表。

    本轮删掉的正是 ``useRunConfig`` 里那张 ``CONFIG_LABELS`` —— 它写"成本预算上限"，
    后端 label 写"最大成本预算"，同一屏两个名字，谁也没错、合起来就是骗人。
    """
    offenders: dict[str, list[str]] = {}
    for spec in _fields():
        if spec.kind == "bool" or spec.key in {"use_tools", "enabled_tools"}:
            continue  # 工具区那两句是界面自己的说明文字，不是字段表
        hits = _hits(spec.label)
        if hits:
            offenders[spec.label] = hits
    assert not offenders, "界面代码行里出现了后端的字段名（该从响应读）：\n" + "\n".join(
        f"  {label} ← {h}" for label, hs in offenders.items() for h in hs
    )


# --------------------------------------------------------------------------- #
# 2. 单位与默认值归后端
# --------------------------------------------------------------------------- #
def test_界面代码行里不许出现单位后缀字面量() -> None:
    """单位在 ``fields[].unit``（方案 §2.1）。写死"轮"的地方每多一处，
    后端改口径时就多一处会静默说谎的地方。"""
    units = {
        spec.unit
        for spec in _fields()
        if spec.unit and spec.kind in ("int", "money", "duration")
    }
    assert units, "后端没给任何单位 ⇒ 这条审计测不到东西，先修契约再谈用例"
    offenders = {unit: _hits(f"'{unit}'") or _hits(f'"{unit}"') for unit in sorted(units)}
    offenders = {unit: hits for unit, hits in offenders.items() if hits}
    assert not offenders, "界面代码行里出现了单位字面量（该读 unit）：\n" + "\n".join(
        f"  {unit} ← {h}" for unit, hs in offenders.items() for h in hs
    )


def test_界面代码行里不许给运行配置补默认值() -> None:
    """``?? 3`` 那一族的墓碑。

    ``max_iterations`` 的 3 以前在界面上写了四处，后端默认却是 5 ——
    那不是"用户没意见"，那是替用户下了一道后端从没收到过的令（方案 §4 P-8）。
    拉不到响应时的正确做法是**整块降级 + 什么都不发**，不是猜一个数。
    """
    #: 两种形状各自一条：① 键名后面紧跟 ``?? 数字``（给这一档补默认值）；
    #: ② 任何 ``?? 3`` / ``?? 5`` / ``?? 7`` —— 这三个数正是后端那一版的默认值，
    #:    界面上出现它们九个字符中的任何一个当兜底，都说明有人又开始替后端决定了。
    _KEY_FALLBACK = re.compile(
        r"(max_iterations|review_threshold|max_cost_cny|timeout_s|rag_top_k)\W{0,8}\?\?\s*\d"
    )
    _BARE_FALLBACK = re.compile(r"\?\?\s*[357]\b")
    offenders: list[str] = []
    for path, lineno, text in _code_lines():
        if _KEY_FALLBACK.search(text) or _BARE_FALLBACK.search(text):
            offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{lineno}: {text}")
    assert not offenders, "界面在给运行配置补默认值：\n" + "\n".join(f"  {h}" for h in offenders)


# --------------------------------------------------------------------------- #
# 3. 行表覆盖：后端说能配的数值键，界面就得有行
# --------------------------------------------------------------------------- #
_PANEL = WEB_SRC / "components" / "RunConfigPanel.tsx"
_ROW_RE = re.compile(r"const (?:BASIC|ADVANCED)_ROWS = \[([^\]]*)\]", re.S)


def _row_keys() -> set[str]:
    text = _PANEL.read_text(encoding="utf-8")
    blocks = _ROW_RE.findall(text)
    assert len(blocks) == 2, f"面板里应当恰好两张行表（基础 / 高级），读到 {len(blocks)} 张"
    return {m.group(1) for block in blocks for m in re.finditer(r"'([\w.]+)'", block)}


def test_后端声明可配的数值键在界面行表里都有() -> None:
    """AD-41 管的是"将来"（后端新加一栏、这一版界面没有行 ⇒ 面板要点名）。
    这条管的是**现在**：本轮已经 accepted+enforced 的数值键，行表里就必须有它。

    ``review_threshold`` 是活例子：后端 ``fields`` 早就声明它收、也执行，
    而前端行表没有 ⇒ 那个输入框根本不存在，"能配"只在后端成立。
    """
    want = {
        spec.key
        for spec in _fields()
        if spec.accepted and spec.kind in ("int", "money", "duration")
    }
    have = _row_keys()
    assert want <= have, f"界面缺行：{sorted(want - have)}（后端说这些能配）"
    # 反方向也钉一次：行表里不许有后端没声明的键 —— 那会画出一个发不出去的控件
    assert have <= want | {"enabled_tools"}, f"行表里有后端没声明的键：{sorted(have - want)}"


def test_行表与数值键集合都不是空的() -> None:
    """前件用例：上面那条如果读到两张空表就会**恒真**。"""
    assert _row_keys(), "行表读出来是空的 —— 多半是那两个 const 改了名，不是通过"
    assert len(RUN_CONFIG_LIMITS) >= 3


@pytest.mark.parametrize("key", sorted(RUN_CONFIG_LIMITS))
def test_每个有界的键后端都给了单位或刻意不给(key: str) -> None:
    """``limits`` 里有界、``fields`` 里却没声明单位的键，界面上就是个**裸数字**。

    现在这样的只有 ``review_threshold`` 之外的 bool/select 类，它们本来不进 limits。
    这条是"契约内部自洽"的自查：加一栏数字时顺手把 unit 写上，
    否则界面会画出一个不知道带什么单位的输入框（少一栏是看得见的缺，多一栏是配了不生效，
    裸数字则是**第三种**：看着能填、填完没人知道它是什么）。
    """
    spec = next((f for f in _fields() if f.key == key), None)
    assert spec is not None, f"{key} 给了界却没在 fields 里声明 ⇒ 界面按纪律不给控件"
    if spec.kind in ("int", "money", "duration"):
        assert spec.unit, f"{key} 是数值键却没有 unit，界面只能画一个裸数字"
