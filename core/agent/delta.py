"""从**流式** JSON 文本里增量抽出一个字符串字段的值。

为什么需要它
------------
``executor`` / ``reviewer`` 都是结构化输出（``invoke_model(..., ExecutorDecision)``），
模型吐出来的是 ``{"thought": "...", "answer": "..."}`` 这种 JSON。要做流式输出，
就得在 JSON 还没写完的时候，把**用户该看的那个字段**（``answer`` / ``final_answer``）
边写边往外发 —— 而不是把 ``"answer":`` 这种键名和引号也一起显示给人看。

为什么不用现成的增量 JSON 解析器
--------------------------------
1. 引入第三方依赖（``ijson`` / ``json-stream``）只为这一个用途，不值得；
2. 它们在**截断**的输入上要么抛错、要么把半个值吞掉，而流式场景里"半个值"
   恰恰是最常见的中间态 —— 本实现按字符状态机走，写一半就发一半，天然耐受截断；
3. 只关心**一个**字符串字段，全文解析是杀鸡用牛刀。

它保证什么、不保证什么
----------------------
* 保证：抽出的文本是**解码后**的正文（`\\n` 变成真换行、`\\u4e2d` 变成「中」），
  不把转义序列当正文显示；
* 保证：**代理对合成一个字符** —— `\\ud83d\\ude00` 出 1 个 emoji，不出两个孤立代理字符。
  这条不是洁癖而是出口要求：``api/events.py`` 用 ``json.dumps(..., ensure_ascii=False)``
  拼 SSE 帧，载荷里只要有一个孤立代理，那一帧就 ``UnicodeEncodeError`` 编不出去，
  用户看到的是答案打到一半整条流断掉（审查报告 CR-06）。等不到另一半的落单代理
  一律吐 ``\\ufffd``（"这一格确实坏过"），既不静默丢也不留脏字符；
* 保证：抽不到就**一声不吭**（下游收到 0 个增量），绝不猜、绝不补占位文本 ——
  模型没按 JSON 出（纯文本降级）时，结果屏退回骨架屏而不是显示一串花括号；
* 不保证：嵌套结构里同名字段的区分（取**第一个**出现在「键位」上的同名键）。
  ``ExecutorDecision`` / ``ReviewVerdict`` 都是扁平契约，够用。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def sanitize_surrogates(text: str) -> str:
    """把字符串里的**孤立代理码点**换成 ``\\ufffd``（其余原样返回）。

    为什么单独有这一条（审查报告 Q6-02，CR-06 的续集）：``json.loads`` 接受
    ``"\\ud83d"`` 这种没配对的代理并原样给出一个 ``chr(0xD83D)``，Python 字符串能装下它，
    但两条出口都装不下 ——
    ① ``api/events.py`` 用 ``json.dumps(..., ensure_ascii=False)`` 拼 SSE 帧再 UTF-8 编码，
    ② SQLite 写 TEXT 时同样按 UTF-8 编码；两处都抛
    ``UnicodeEncodeError: ... surrogates not allowed``。
    流式抽取器（:class:`JsonFieldDelta`）只护住了它自己那一条出口，
    节点增量与终态落库这两条走的是模型 JSON 的**全文解析**结果，同一个雷还在。

    与 :class:`JsonFieldDelta` 的口径一致：坏掉的那一格吐 ``\\ufffd``（"这里确实坏过"），
    既不静默丢字符，也不留一个把整帧打爆的脏码点。

    前提：Python 的 ``str`` 存的是码点，**不可能**存在"配好对的代理"（那会是一个
    ``> 0xFFFF`` 的码点），所以落在 ``D800-DFFF`` 区间的一律是落单的。
    """
    if not any("\ud800" <= char <= "\udfff" for char in text):
        return text  # 快路径：99.99% 的字符串走到这里就原样返回，不新建一份
    return "".join("\ufffd" if "\ud800" <= char <= "\udfff" else char for char in text)


def sanitize_surrogates_deep(value: Any) -> Any:
    """递归版：把 dict / list / tuple / str 里所有字符串都过一遍 :func:`sanitize_surrogates`。

    给 ``sanitize_update`` 用（节点增量是嵌套 dict，模型正文可能出现在任意一层）。
    非字符串叶子原样透传 —— 它只负责把脏码点洗掉，不改变任何结构或类型。
    """
    if isinstance(value, str):
        return sanitize_surrogates(value)
    if isinstance(value, dict):
        return {
            (sanitize_surrogates(key) if isinstance(key, str) else key): sanitize_surrogates_deep(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        cleaned = [sanitize_surrogates_deep(item) for item in value]
        return type(value)(cleaned) if isinstance(value, tuple) else cleaned
    return value


#: JSON 字符串转义表（``\uXXXX`` 单独处理，因为它要吃 4 个字符）
_ESCAPES: dict[str, str] = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}

# 状态机的四个状态
_S_KEY = 0  # 找键名（形如 "answer"）
_S_COLON = 1  # 键名之后找冒号
_S_QUOTE = 2  # 冒号之后找起始引号
_S_VALUE = 3  # 正在读字符串正文
_S_DONE = 4  # 读完 / 放弃

#: 键名只有出现在这些字符之后才算「键位」（排除正文里恰好出现同名串的误命中）
_KEY_AFTER = ("", "{", ",")


class JsonFieldDelta:
    """边喂流式文本、边吐某个字符串字段的增量。

    用法::

        streamer = JsonFieldDelta("answer", sink)
        decision = llm.invoke_model(ask, ExecutorDecision, on_text=streamer.feed)

    状态机是**逐字符**的：一次 ``feed`` 可以是一整个块，也可以是半个字，
    跨块的转义序列（``\\`` 在块尾、``n`` 在块头）也能正确接上。
    """

    __slots__ = ("_escaping", "_hi", "_hex", "_key", "_match", "_prev", "_sink", "_state", "chars")

    def __init__(self, field: str, sink: Callable[[str], None]) -> None:
        """绑定目标字段名与下游出口。

        Args:
            field: 要抽的字段名（**不带引号**），如 ``"answer"``。
            sink: 增量回调；收到的是解码后的正文片段。
        """
        self._key = f'"{field}"'
        self._sink = sink
        self._state = _S_KEY
        self._match = 0
        self._prev = ""  # 上一个**非空白**字符，用来判断是不是键位
        self._escaping = False
        self._hex: list[str] | None = None
        #: 攒着**还没等到另一半**的高代理（``\uD800``–``\uDBFF``）。
        #: 必须是实例状态而不是局部变量：代理对最常见的到达形状就是被 chunk 从中间劈开。
        self._hi: int | None = None
        #: 已吐出的字符数（调用方用它判断"这一步到底吐了东西没有"）
        self.chars = 0

    @property
    def done(self) -> bool:
        """是否已经读完 / 放弃（读完之后再喂文本也不会再产出增量）。"""
        return self._state == _S_DONE

    def feed(self, text: str) -> None:
        """喂进一段新到达的流式文本，同步把新抽出的正文交给 ``sink``。

        Args:
            text: 本次到达的原始文本（可能包含键名、引号、转义等 JSON 噪声）。
        """
        if not text or self._state == _S_DONE:
            return
        out: list[str] = []
        for ch in text:
            state = self._state

            if state == _S_KEY:
                if ch.isspace():
                    continue
                if ch == '"' and self._prev in _KEY_AFTER:
                    self._match = 1
                    if len(self._key) == 1:  # pragma: no cover - 字段名不可能为空
                        self._state = _S_COLON
                elif self._match and ch == self._key[self._match]:
                    self._match += 1
                    if self._match >= len(self._key):
                        self._state = _S_COLON
                        self._match = 0
                else:
                    self._match = 0
                    if ch == '"' and self._prev in _KEY_AFTER:
                        self._match = 1
                self._prev = ch
                continue

            if state == _S_COLON:
                if ch.isspace():
                    continue
                if ch == ":":
                    self._state = _S_QUOTE
                    continue
                # 不是冒号 ⇒ 刚才匹配到的不是键（或这个字段不是字符串）⇒ 放弃
                self._state = _S_DONE
                break

            if state == _S_QUOTE:
                if ch.isspace():
                    continue
                if ch == '"':
                    self._state = _S_VALUE
                    continue
                self._state = _S_DONE  # 值不是字符串（数字 / 对象 / 数组）
                break

            # state == _S_VALUE
            if self._hex is not None:
                self._hex.append(ch)
                if len(self._hex) == 4:
                    raw = "".join(self._hex)
                    self._hex = None
                    self._escaping = False
                    try:
                        code = int(raw, 16)
                    except ValueError:  # pragma: no cover - 非法 \uXXXX
                        # 乱码转义：先把攒着的高代理冲出去（它永远等不到另一半了），
                        # 再按原样吐这段文本 —— 不猜、不补。
                        self._flush_lone_high(out)
                        out.append(f"\\u{raw}")
                    else:
                        self._push_code(code, out)
                continue
            if self._escaping:
                if ch == "u":
                    self._hex = []
                else:
                    # 这是一个简单转义（\n \" \\ …），不是 \uXXXX ⇒ 攒着的高代理彻底配不上了
                    self._flush_lone_high(out)
                    out.append(_ESCAPES.get(ch, ch))
                    self._escaping = False
                continue
            if ch == "\\":
                self._escaping = True
                continue
            if ch == '"':
                # 正文到此结束：攒着的高代理再也等不到另一半了，必须冲出去（丢掉=少一个字，
                # 留着=下一段正文开头冒出一个错位的替换符，两种都比"承认这里坏过"更糟）。
                self._flush_lone_high(out)
                self._state = _S_DONE
                break
            # 普通正文字符：同理，它把攒着的高代理变成了"落单"
            self._flush_lone_high(out)
            out.append(ch)

        if out:
            text_out = "".join(out)
            self.chars += len(text_out)
            self._sink(text_out)

    # ------------------------------------------------------------------ #
    # 代理对：出口要求它必须是"一个字符"或"\ufffd"，绝不允许孤立代理
    # ------------------------------------------------------------------ #

    def _flush_lone_high(self, out: list[str]) -> None:
        """把攒着的高代理按"坏了一格"处理（吐 ``\\ufffd``），没攒东西就什么都不做。"""
        if self._hi is not None:
            self._hi = None
            out.append("\ufffd")

    def _push_code(self, code: int, out: list[str]) -> None:
        """收下 ``\\uXXXX`` 解出的码点：该合成就成就，该认错就认错。

        三种情况都要管，因为流式里三种都会真的出现：
        低代理成对到达（成就一个星价体字符）、低代理**没有**前配（认错一格）、
        高代理后面跟的不是低代理（前一格认错，再处理这一格）。
        """
        if 0xDC00 <= code <= 0xDFFF:  # 低代理
            if self._hi is None:
                out.append("\ufffd")  # 落单的低代理：这一格本来就是脏的
            else:
                high = self._hi
                self._hi = None
                # 移位是 <<10（低代理有 10 位空间 = 0x400），不是 <<16：
                # 按 <<16 算会得到 > U+10FFFF 的数，chr() 直接 ValueError（本轮真踩过，
                # 被 tests/unit/test_agent_delta.py 当场拦下）。
                out.append(chr(0x10000 + ((high - 0xD800) << 10) + (code - 0xDC00)))
            return
        if 0xD800 <= code <= 0xDBFF:  # 高代理：先攒着，等下一段
            self._flush_lone_high(out)  # 连续两个高代理 ⇒ 前一个永远配不上
            self._hi = code
            return
        self._flush_lone_high(out)  # 普通码点 ⇒ 前面那个高代理落单了
        out.append(chr(code))


__all__ = [
    "JsonFieldDelta",
    "sanitize_surrogates",
    "sanitize_surrogates_deep",
]
