"""web_search：网页搜索，后端可插拔。

默认后端抓 DuckDuckGo 的 HTML 端点（不引第三方搜索 SDK）。三条原则：

1. **不伪造结果**：搜索不通就抛 :class:`SearchError`，由注册表记成 ``failed``，
   绝不用模型记忆凑几条假链接；
2. **后端可替换**：测试与私有部署通过 :func:`set_search_backend` 注入自建后端，
   或用环境变量 ``WEB_SEARCH_BACKEND=none`` 直接关掉；
3. **零额外依赖**：用 ``httpx`` + 标准库 ``html.parser`` 解析，不引 bs4 / lxml。
"""

from __future__ import annotations

import html
import logging
import os
import urllib.parse
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Annotated

import httpx
from pydantic import Field

from core.tools.registry import ToolRegistry, ToolSpec

logger = logging.getLogger(__name__)

#: DuckDuckGo 的 HTML 端点（无 JS、结构稳定、不需要 key）
DDG_ENDPOINT = "https://html.duckduckgo.com/html/"
USER_AGENT = "Mozilla/5.0 (compatible; trinity/0.1)"
#: 单次 HTTP 请求超时（秒）
REQUEST_TIMEOUT = 8.0
#: 单条摘要截断长度
MAX_SNIPPET_CHARS = 240
#: 环境变量：设为 none / off / disabled 时关闭搜索
BACKEND_ENV = "WEB_SEARCH_BACKEND"

SearchHit = dict[str, str]
SearchBackend = Callable[[str, int], list[SearchHit]]


class SearchError(RuntimeError):
    """搜索后端不可用或返回为空。"""


_BACKEND: SearchBackend | None = None


def set_search_backend(backend: SearchBackend | None) -> None:
    """注入搜索后端；传 ``None`` 恢复默认的 DuckDuckGo 后端。"""
    global _BACKEND
    _BACKEND = backend


def _unwrap(href: str) -> str:
    """把 DuckDuckGo 的 ``/l/?uddg=`` 跳转链接还原成真实地址。"""
    if href.startswith("http"):
        return href
    parsed = urllib.parse.urlparse(href)
    query = urllib.parse.parse_qs(parsed.query)
    target = query.get("uddg", [""])[0]
    return urllib.parse.unquote(target) if target else href


class _DdgParser(HTMLParser):
    """从 DuckDuckGo 结果页里抽取标题 / 链接 / 摘要。

    页面结构：每个结果是一个带 ``result__a`` 的 ``<a>``（标题），紧随其后有
    ``result__snippet``（摘要）。这里不依赖嵌套层级，只按 class 抓，抗小幅改版。
    """

    def __init__(self) -> None:
        super().__init__()
        self.hits: list[SearchHit] = []
        self._current: SearchHit | None = None
        self._capture: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = dict(attrs).get("class", "") or ""
        if tag == "a" and "result__a" in classes:
            self._flush()
            self._current = {
                "title": "",
                "url": _unwrap(dict(attrs).get("href", "") or ""),
                "snippet": "",
            }
            self._capture = "title"
        elif self._current is not None and "result__snippet" in classes:
            self._capture = "snippet"

    def handle_data(self, data: str) -> None:
        if self._capture and self._current is not None:
            key = self._capture
            self._current[key] = (self._current[key] + html.unescape(data)).strip()

    def handle_endtag(self, tag: str) -> None:
        title_done = self._capture == "title" and tag == "a"
        snippet_done = self._capture == "snippet" and tag in {"a", "div"}
        if title_done or snippet_done:
            self._capture = None

    def close(self) -> None:
        self._flush()
        super().close()

    def _flush(self) -> None:
        if self._current is not None and self._current["title"]:
            self.hits.append(self._current)
        self._current = None
        self._capture = None


def _duckduckgo_backend(query: str, num_results: int) -> list[SearchHit]:
    """默认后端：抓 DuckDuckGo HTML 结果页。"""
    try:
        response = httpx.get(
            DDG_ENDPOINT,
            params={"q": query},
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SearchError(f"搜索请求失败：{type(exc).__name__}: {exc}") from exc

    parser = _DdgParser()
    parser.feed(response.text)
    parser.close()
    hits = parser.hits[: max(1, num_results)]
    if not hits:
        raise SearchError("搜索服务返回空结果（可能被限流或页面结构已变化）")
    return hits


def resolve_backend() -> SearchBackend:
    """决定用哪个后端。

    Raises:
        SearchError: 后端被环境变量关闭。
    """
    if _BACKEND is not None:
        return _BACKEND
    if os.environ.get(BACKEND_ENV, "").strip().lower() in {"none", "off", "disabled"}:
        raise SearchError(f"搜索后端已被环境变量 {BACKEND_ENV} 关闭")
    return _duckduckgo_backend


def web_search(
    query: Annotated[str, Field(description="搜索关键词，用自然语言描述要查什么")],
    num_results: Annotated[
        int,
        Field(ge=1, le=10, description="返回结果条数，1-10，默认 5"),
    ] = 5,
) -> str:
    """搜索网页，返回标题、链接与摘要（事实性、时效性问题优先用它，不要凭记忆作答）。"""
    keyword = query.strip()
    if not keyword:
        raise SearchError("搜索关键词不能为空")
    hits = resolve_backend()(keyword, num_results)
    lines = []
    for index, hit in enumerate(hits, 1):
        snippet = hit.get("snippet", "")[:MAX_SNIPPET_CHARS] or "（无摘要）"
        lines.append(f"{index}. {hit.get('title', '')}\n   {hit.get('url', '')}\n   {snippet}")
    return f"「{keyword}」共 {len(hits)} 条结果：\n" + "\n".join(lines)


def register(registry: ToolRegistry) -> ToolSpec:
    """把 web_search 注册进给定注册表。"""
    return registry.register(
        web_search,
        name="web_search",
        description=(
            "联网搜索网页并返回标题、链接与摘要。需要最新事实、外部数据或不确定的信息时使用；"
            "搜索失败会如实报错，不要据此编造内容"
        ),
        danger_level="low",
        timeout=15,
        retry=2,
    )


__all__ = [
    "BACKEND_ENV",
    "DDG_ENDPOINT",
    "SearchBackend",
    "SearchError",
    "SearchHit",
    "register",
    "resolve_backend",
    "set_search_backend",
    "web_search",
]
