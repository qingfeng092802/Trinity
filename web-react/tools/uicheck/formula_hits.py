"""真实答案里的「公式形态」命中率 —— 决定要不要上 KaTeX 的唯一依据。

只读打开 sqlite（mode=ro），一条 SQL 都不写。
跑法：python web-react/tools/uicheck/formula_hits.py
"""
import re
import sqlite3

DBS = ("data/trinity.db", "data/trinity_1.db")

BRACE = r"[_\^]\s*\{[^{}]*\}"
MACRO = r"\\" + r"(?:sum|sqrt|frac|cdot|Delta|alpha|beta|eta|gamma|mu|lambda|rho|sigma|theta|times|approx|le|ge|ne)"
SYM = "[∑Σ∏∫√]"

SHAPES = {
    "$…$ 包裹的 LaTeX": re.compile(r"\$[^$\n]{2,}\$"),
    r"\frac{}{}": re.compile(r"\\" + "frac"),
    "任意 LaTeX 宏(\\cdot 等)": re.compile(MACRO),
    "Unicode 算符 Σ∫√": re.compile(SYM),
    "带花括号下标 _{..}": re.compile(BRACE),
    "裸下划线 a_b（snake_case 风险）": re.compile(r"\w_\w"),
    "带空格除号 A / B": re.compile(r"\S\s/\s\S"),
    "行内反引号里含公式特征": re.compile(r"`[^`\n]*(?:" + BRACE + r"|\\" + "frac|" + SYM + ")[^`\n]*`"),
    "围栏里含公式特征": re.compile(
        r"```[^\n]*\n(?:[^\n]*\n)*?[^\n`]*(?:" + BRACE + r"|\\" + "frac|" + SYM + ")[^`\n]*\n```"
    ),
}
ANY_MATH = re.compile(BRACE + r"|\\" + "frac|" + SYM)


def main() -> None:
    for db in DBS:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = [
            r[0]
            for r in conn.execute(
                "select final_answer from tasks "
                "where final_answer is not null and length(final_answer) > 40"
            )
        ]
        conn.close()
        print(f"\n== {db} —— 有答案的任务 {len(rows)} 条")
        for name, rx in SHAPES.items():
            hits = [r for r in rows if rx.search(r)]
            print(f"  {name:<34}{len(hits):>4}/{len(rows)}")
        cand = [r for r in rows if ANY_MATH.search(r)]
        print(f"  —— 含任一算式特征：{len(cand)}/{len(rows)}")
        for r in cand[:3]:
            line = next(
                (l for l in r.splitlines() if ANY_MATH.search(l) or re.search(r"\S\s/\s\S", l)),
                "",
            )
            print(f"     样本: {line[:160]}")


if __name__ == "__main__":
    main()
