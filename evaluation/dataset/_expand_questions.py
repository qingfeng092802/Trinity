"""评测集扩充：26 → 50 题（**零编造**，每题关键词必须逐字命中原文）。

用法::

    python evaluation/dataset/_expand_questions.py --check   # 只校验（用装好依赖的解释器）
    python evaluation/dataset/_expand_questions.py --write   # 校验通过后追加

纪律（用户红线：严禁伪造数字或编造文档中不存在的答案）：

* 每题的 ``expect_keywords`` 每一项都必须在 ``expect_document`` 的**原文里逐字出现**，
  由 :func:`verify` 用朴素子串匹配硬性校验，任一项不过就整体拒绝写入。
* 题目只覆盖 ``evaluation/fixtures/`` 下 4 篇真实文档，不引入外部知识。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = PROJECT_ROOT / "evaluation" / "fixtures"
DATASET = PROJECT_ROOT / "evaluation" / "dataset" / "knowledge_eval.jsonl"

#: 新增 24 题（q27–q50）。分布目标：
#: anfangjiankong 7→13、menjinyikatong 8→13、zonghebuxian 6→12、jifangguangbo 5→12
NEW_ROWS: list[dict[str, object]] = [
    # ---------------- anfangjiankong.md（+6） ----------------
    {
        "id": "q27",
        "type": "参数",
        "query": "室内半球摄像机的安装高度范围是多少",
        "expect_document": "anfangjiankong.md",
        "expect_keywords": ["2.8", "3.2"],
    },
    {
        "id": "q28",
        "type": "参数",
        "query": "硬盘容量计算要预留百分之多少冗余",
        "expect_document": "anfangjiankong.md",
        "expect_keywords": ["20%"],
    },
    {
        "id": "q29",
        "type": "参数",
        "query": "监控网络带宽按多少倍冗余设计",
        "expect_document": "anfangjiankong.md",
        "expect_keywords": ["1.5 倍"],
    },
    {
        "id": "q30",
        "type": "参数",
        "query": "监控中心显示墙支持多少画面分割",
        "expect_document": "anfangjiankong.md",
        "expect_keywords": ["16 画面"],
    },
    {
        "id": "q31",
        "type": "流程",
        "query": "监控网络如何实现与办公网的隔离",
        "expect_document": "anfangjiankong.md",
        "expect_keywords": ["独立 VLAN"],
    },
    {
        "id": "q32",
        "type": "流程",
        "query": "摄像机点位需要覆盖哪些区域",
        "expect_document": "anfangjiankong.md",
        "expect_keywords": ["电梯厅", "地下车库"],
    },
    # ---------------- menjinyikatong.md（+5） ----------------
    {
        "id": "q33",
        "type": "参数",
        "query": "门禁开门延时可以在什么范围内调整",
        "expect_document": "menjinyikatong.md",
        "expect_keywords": ["3", "10"],
    },
    {
        "id": "q34",
        "type": "参数",
        "query": "控制器本地至少存储多少条通行记录",
        "expect_document": "menjinyikatong.md",
        "expect_keywords": ["10 万条"],
    },
    {
        "id": "q35",
        "type": "参数",
        "query": "断电后通行记录依靠什么保持多少天",
        "expect_document": "menjinyikatong.md",
        "expect_keywords": ["主板电池", "30 天"],
    },
    {
        "id": "q36",
        "type": "术语缩写",
        "query": "门禁读卡器符合哪种 ISO 协议",
        "expect_document": "menjinyikatong.md",
        "expect_keywords": ["ISO14443", "TypeA"],
    },
    {
        "id": "q37",
        "type": "参数",
        "query": "玻璃门和木门分别采用什么电锁",
        "expect_document": "menjinyikatong.md",
        "expect_keywords": ["电插口锁", "阴极锁"],
    },
    # ---------------- zonghebuxian.md（+6） ----------------
    {
        "id": "q38",
        "type": "参数",
        "query": "加上两端跳线后信道总长度不超过多少",
        "expect_document": "zonghebuxian.md",
        "expect_keywords": ["100 米"],
    },
    {
        "id": "q39",
        "type": "参数",
        "query": "施工时线缆拉力不能超过多少牛顿",
        "expect_document": "zonghebuxian.md",
        "expect_keywords": ["110 牛顿"],
    },
    {
        "id": "q40",
        "type": "参数",
        "query": "桥架水平偏差每米不超过多少毫米",
        "expect_document": "zonghebuxian.md",
        "expect_keywords": ["2 毫米"],
    },
    {
        "id": "q41",
        "type": "参数",
        "query": "机柜安装垂直偏差不大于多少毫米",
        "expect_document": "zonghebuxian.md",
        "expect_keywords": ["3 毫米"],
    },
    {
        "id": "q42",
        "type": "参数",
        "query": "机柜内线缆绑扎间距是多少毫米",
        "expect_document": "zonghebuxian.md",
        "expect_keywords": ["300", "400"],
    },
    {
        "id": "q43",
        "type": "流程",
        "query": "强弱电线缆无法分槽敷设时怎么处理",
        "expect_document": "zonghebuxian.md",
        "expect_keywords": ["金属隔板"],
    },
    # ---------------- jifangguangbo.md（+7） ----------------
    {
        "id": "q44",
        "type": "参数",
        "query": "机房相对湿度应控制在什么范围",
        "expect_document": "jifangguangbo.md",
        "expect_keywords": ["40%", "60%"],
    },
    {
        "id": "q45",
        "type": "参数",
        "query": "防静电地板铺设偏差每米不大于多少",
        "expect_document": "jifangguangbo.md",
        "expect_keywords": ["1 毫米"],
    },
    {
        "id": "q46",
        "type": "流程",
        "query": "UPS 电池组多久进行一次放电测试",
        "expect_document": "jifangguangbo.md",
        "expect_keywords": ["每季度"],
    },
    {
        "id": "q47",
        "type": "参数",
        "query": "机房采用独立接地时接地电阻不大于多少",
        "expect_document": "jifangguangbo.md",
        "expect_keywords": ["4 欧姆"],
    },
    {
        "id": "q48",
        "type": "参数",
        "query": "机柜排列形成的冷通道宽度不小于多少",
        "expect_document": "jifangguangbo.md",
        "expect_keywords": ["1.2 米"],
    },
    {
        "id": "q49",
        "type": "参数",
        "query": "背景音乐广播采用定压多少伏传输",
        "expect_document": "jifangguangbo.md",
        "expect_keywords": ["100 伏"],
    },
    {
        "id": "q50",
        "type": "参数",
        "query": "走廊扬声器间距不大于多少米",
        "expect_document": "jifangguangbo.md",
        "expect_keywords": ["15 米"],
    },
]


def load_existing() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in DATASET.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def verify(rows: list[dict[str, object]]) -> list[str]:
    """逐条校验：每个关键词必须在目标文档原文里逐字出现。返回问题列表。"""
    problems: list[str] = []
    cache: dict[str, str] = {}
    seen_ids: set[str] = set()

    for row in rows:
        doc = str(row["expect_document"])
        if doc not in cache:
            path = FIXTURES / doc
            if not path.exists():
                problems.append(f"{row['id']}: 文档不存在 {doc}")
                continue
            cache[doc] = path.read_text(encoding="utf-8")
        text = cache[doc]

        rid = str(row["id"])
        if rid in seen_ids:
            problems.append(f"{rid}: id 重复")
        seen_ids.add(rid)

        for kw in row["expect_keywords"]:  # type: ignore[union-attr]
            if str(kw) not in text:
                problems.append(f"{rid}: 关键词「{kw}」未逐字命中 {doc}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只校验，不写入")
    parser.add_argument("--write", action="store_true", help="校验通过后追加到数据集")
    args = parser.parse_args()

    existing = load_existing()
    existing_ids = {str(r["id"]) for r in existing}
    dup = sorted(existing_ids & {str(r["id"]) for r in NEW_ROWS})
    if dup:
        print(f"[FAIL] 与现有题目 id 冲突：{dup}")
        return 1

    problems = verify(NEW_ROWS)
    if problems:
        print(f"[FAIL] 校验未通过（{len(problems)} 项）：")
        for p in problems:
            print("  -", p)
        return 1

    print(f"[OK] 新增 {len(NEW_ROWS)} 题全部通过原文逐字校验")
    print(f"     现有 {len(existing)} 题 → 写入后 {len(existing) + len(NEW_ROWS)} 题")

    if args.write:
        with DATASET.open("a", encoding="utf-8") as fh:
            for row in NEW_ROWS:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"[WRITE] 已追加到 {DATASET}")
    elif not args.check:
        print("（未指定 --write，未写入）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
