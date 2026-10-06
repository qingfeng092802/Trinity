r"""`core/agent/delta.py` 的 `JsonFieldDelta` —— 逐字符状态机的纯函数用例。

为什么这一层值得单独钉
----------------------
它是"结果流式输出"的地基：模型吐的是 JSON（``{"thought":…,"answer":…}``），
要把 ``answer`` 的正文边到边发给前端，就得在 JSON 还没写完的时候从**半个 JSON** 里抽字符串。
这条通道此前**全仓零覆盖**（``grep -rn JsonFieldDelta tests/`` 空），而它的失效不是"报错"，
是**发出去的 SSE 帧压根编不成 UTF-8** —— ``api/events.py:150`` 用 ``ensure_ascii=False``
序列化载荷，一个孤立代理字符就让 ``str.encode('utf-8')`` 直接抛 ``UnicodeEncodeError``，
用户看到的是答案打到一半断流（审查报告 CR-06，甲档复现）。

⚠️ 本文件所有 JSON 串一律写成 **raw 字符串**（``r'…'``）。
这不是风格：上一版用普通字符串，Python 在**编译期**就把 ``\ud83d`` 解成了孤立代理字符，
测试文件自己先在 assertion-rewrite 阶段抛 ``UnicodeEncodeError`` 崩在 collect ——
"源码里写不出这个输入"这件事本身就是 CR-06 最好的注脚。被测的是"JSON 文本里有
``\ud83d\ude00`` 这串转义"，所以源码里必须是**字面**的那 12 个字符。
"""

from __future__ import annotations

import json

import pytest

from core.agent.delta import JsonFieldDelta


def extract(src: str, *, field: str = "answer", chunk: int = 1) -> str:
    r"""按 ``chunk`` 大小喂 ``src``，返回 sink 收到的全部正文。

    ``chunk=1`` 是刻意选的最严形状：跨块的转义序列（``\`` 落在块尾、``n`` 落在块头）
    与跨块的代理对都被覆盖。整块一次喂的路径也要跑（见下面对照用例），
    两条路共用一套期望值才有意义。
    """
    got: list[str] = []
    streamer = JsonFieldDelta(field, got.append)
    for i in range(0, len(src), chunk):
        streamer.feed(src[i : i + chunk])
    return "".join(got)


#: 一个 emoji 的 JSON 转义写法（上游按 ensure_ascii=True 发过来就是这个形状）
EMOJI_ESC = r"\ud83d\ude00"


# --------------------------------------------------------------------------- #
# 转义解码：抽出来的是**正文**，不是 JSON 噪声
# --------------------------------------------------------------------------- #

def test_基本字段与噪声剥离() -> None:
    assert extract(r'{"thought": "t", "answer": "A"}') == "A"


def test_普通转义序列解码成正文() -> None:
    assert extract(r'{"answer": "a\nb\\c\"d"}') == "a\nb\\c\"d"


def test_中文_XXXX_转义逐字解码() -> None:
    assert extract(r'{"answer": "\u4e2d\u6587"}') == "中文"


def test_整块一次性喂与逐字符喂结果相同() -> None:
    src = r'{"answer": "\u4e2d' + EMOJI_ESC + r'\n"}'
    assert extract(src, chunk=1) == extract(src, chunk=len(src))


# --------------------------------------------------------------------------- #
# CR-06 本体：代理对必须合成**一个**字符，绝不许留下孤立代理
# --------------------------------------------------------------------------- #

def test_星价体代理对合成一个字() -> None:
    r"""``\ud83d\ude00`` 是一个 emoji（😀），不是两个字符。

    ``json.loads`` 给的是长度 1；旧实现各 ``chr()`` 一次 ⇒ 长度 2 且全是孤立代理。
    """
    src = r'{"answer": "' + EMOJI_ESC + r' hi"}'
    out = extract(src)
    assert out == "\U0001F600 hi"
    assert len(out) == 4  # 1 个 emoji + 空格 + h + i
    # 与标准库解析对齐：同一串输入，两条路必须给同一个答案
    assert out == json.loads(src)["answer"]


def test_代理对跨两次喂也接得上() -> None:
    r"""高代理在一个 chunk 尾、低代理在下一个 chunk 头 —— 真实流式的到达形状。"""
    got: list[str] = []
    streamer = JsonFieldDelta("answer", got.append)
    streamer.feed(r'{"answer": "\ud83d')
    streamer.feed(r'\ude00"}')
    assert "".join(got) == "\U0001F600"


def test_代理对不许产出无法编码的串() -> None:
    """这条是 CR-06 的**病灶本体**：坏的不是"少一个字"，是整条流发不出去。"""
    src = r'{"answer": "' + EMOJI_ESC + r'"}'
    extract(src).encode("utf-8")  # 旧实现在这里抛 UnicodeEncodeError: surrogates not allowed


def test_落单的高代理吐替换符而不是吞掉() -> None:
    r"""高代理后面跟的不是低代理 ⇒ 先吐 ``\ufffd``（这一格确实坏过），再正常处理后面的字。"""
    assert extract(r'{"answer": "\ud83dx"}') == "\ufffdx"


def test_落单的高代理后面跟简单转义也要先认错() -> None:
    r"""上面那条只测了"后面跟普通字符"。跟 ``\n`` 走的是另一条分支（``_escaping``），
    当初就是这条漏了没冲：替换符会跑到换行**后面**去，等于把错位留给了用户读的那一屏。"""
    assert extract(r'{"answer": "\ud83d\nx"}') == "\ufffd\nx"


def test_连续两个高代理前一个认错后一个继续攒() -> None:
    r"""``\ud83d\ud83dx``：第二个也是**高**代理 ⇒ 第一个认错，第二个继续等；
    等到的是 ``x`` ⇒ 第二个也认错。净结果 = 两个替换符 + x。"""
    assert extract(r'{"answer": "\ud83d\ud83dx"}') == "\ufffd\ufffdx"


def test_落单的低代理吐替换符() -> None:
    assert extract(r'{"answer": "\ude00y"}') == "\ufffdy"


def test_值结束时的落单高代理也要冲出去() -> None:
    r"""``\ud83d"``：代理对没等到另一半就遇到收尾引号 ⇒ 不许静默丢掉那一格。"""
    assert extract(r'{"answer": "a\ud83d"}') == "a\ufffd"


# --------------------------------------------------------------------------- #
# 与 SSE 帧的接缝：抽出来的东西必须真能写成帧（把 bug 钉在出口上）
# --------------------------------------------------------------------------- #

def test_抽出的正文能进_SSE_帧并被编码() -> None:
    r"""复现 CR-06 的完整链路：delta 抽取 → ``format_frame`` → ``str.encode('utf-8')``。

    只测 ``extract()`` 的返回值不够 —— 真正的故障发生在 ``api/events.py`` 那一步，
    所以这里直接把帧写出来编码一次。
    """
    from api.events import StreamEvent, format_frame

    src = json.dumps({"answer": "\U0001F600 好了"}, ensure_ascii=True)
    assert EMOJI_ESC in src  # 前件：这串上游确实是按代理对转义发过来的，不然这条测了个空
    frame = format_frame(
        StreamEvent(task_id="t1", name="delta", seq=1, data={"text": extract(src)})
    )
    assert frame.encode("utf-8").decode("utf-8") == frame  # 不许抛、也不许变形
    assert "\U0001F600 好了" in frame


# --------------------------------------------------------------------------- #
# 既有契约不许被这次修复带跑
# --------------------------------------------------------------------------- #

def test_截断的输入按已知行为吐半个值不报错() -> None:
    """主路径的设计目标：写一半就发一半，天然耐受截断（别改这条）。"""
    assert extract(r'{"answer": "写了一半') == "写了一半"


def test_非字符串值时一声不吭且不再找同名键() -> None:
    """**已知契约**（不是这次要修的）：首个键位命中的值不是字符串 ⇒ 直接 latch 到 DONE。

    记在这里是因为它和代理对共用那半段状态机：``json.loads`` 能从
    ``{"answer": null, "answer": "REAL"}`` 里拿到 ``REAL``，而本实现拿不到。
    改这一条要单独拍板（审查报告 P2-1），本用例只钉"今天确实是这个行为"。
    """
    assert extract(r'{"answer": null, "answer": "REAL"}') == ""


def test_纯文本降级时抽不到东西也不许抛() -> None:
    assert extract("直接一句话回答，没有 JSON。") == ""


def test_chars_数的是真正吐出的字符数() -> None:
    r"""代理对合成一个字之后 ``chars`` 也必须按 1 计（它被拿去判"这一步吐没吐东西"）。"""
    got: list[str] = []
    streamer = JsonFieldDelta("answer", got.append)
    streamer.feed(r'{"answer": "' + EMOJI_ESC + r'"}')
    assert streamer.chars == 1


def test_非法十六进制转义按原样吐出不崩() -> None:
    assert extract(r'{"answer": "\uZZZZ"}') == r"\uZZZZ"


@pytest.mark.parametrize("body", [EMOJI_ESC, r"\u4e2d", r"a\nb", r"\ud83d\ude00\ud83d\ude01"])
def test_参数化_各种转义抽出来都能编码(body: str) -> None:
    assert extract(r'{"answer": "' + body + r'"}').encode("utf-8")


# --------------------------------------------------------------------------- #
# Q6-02（2026-10-02）：CR-06 只护住了 delta 这一条出口。同一个雷另外两条在 ——
# SSE 的 ``node`` 帧（载荷是全文解析出来的 update）与 ``mark_terminal`` 写 tasks 行。
# 下面三条钉的是"洗过之后两条出口都不抛"，并且**当场证明没洗会抛**（负面对照）。
# --------------------------------------------------------------------------- #
def _lone_surrogate() -> str:
    r"""从 JSON 文本里解出一个孤立代理 —— ``json.loads`` 不报错，Python str 装得下。"""
    return json.loads(r'"\ud83d"')


def test_落单代理洗成替换符() -> None:
    from core.agent.delta import sanitize_surrogates

    dirty = _lone_surrogate()
    assert "\ud800" <= dirty <= "\udfff", "前置条件：拿到的必须真是孤立代理"
    assert sanitize_surrogates(dirty) == "\ufffd"
    assert sanitize_surrogates("正常中文 + emoji \U0001f600") == "正常中文 + emoji \U0001f600"


def test_洗过的两条出口都不抛_没洗的两条都抛() -> None:
    import sqlite3

    from core.agent.delta import sanitize_surrogates

    dirty = _lone_surrogate()
    clean = sanitize_surrogates(dirty)

    # 出口①：SSE 帧（api/events.py 的 json.dumps(ensure_ascii=False) + UTF-8 编码）
    json.dumps({"answer": clean}, ensure_ascii=False).encode("utf-8")
    with pytest.raises(UnicodeEncodeError):
        json.dumps({"answer": dirty}, ensure_ascii=False).encode("utf-8")

    # 出口②：SQLite 的 TEXT 列
    conn = sqlite3.connect(":memory:")
    conn.execute("create table t(v text)")
    conn.execute("insert into t(v) values (?)", (clean,))
    assert conn.execute("select v from t").fetchone()[0] == "\ufffd"
    with pytest.raises(UnicodeEncodeError):
        conn.execute("insert into t(v) values (?)", (dirty,))


def test_节点增量递归清洗_sanitize_update() -> None:
    """``sanitize_update`` 出来的那份必须能进 SSE 帧（嵌套 dict/list 也要洗）。"""
    from api.runner import sanitize_update

    dirty = _lone_surrogate()
    out = sanitize_update(
        {"final_answer": "好" + dirty, "steps": [{"text": dirty}], "count": 2, "messages": ["脏"]}
    )
    assert out["final_answer"] == "好\ufffd"
    assert out["steps"][0]["text"] == "\ufffd"
    assert out["count"] == 2, "非字符串叶子原样透传"
    assert "messages" not in out, "剔 messages 这条纪律不受影响"
    json.dumps(out, ensure_ascii=False).encode("utf-8")
