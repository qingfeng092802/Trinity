"""file_io：沙箱工作区内的文件读写。

所有路径都必须落在 ``settings.workspace_dir``（默认 ``data/workspace``）内，
``../`` 逃逸和指向外部的绝对路径会被 :class:`SandboxPathError` 直接拒绝。
读写都有长度上限，避免一次调用把上下文撑爆。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from core.tools.registry import ToolRegistry, ToolSpec
from core.tools.sandbox import resolve_workspace_path, workspace_root

#: 单次读取返回的最大字符数
MAX_READ_CHARS = 8000
#: 单次写入的最大字符数
MAX_WRITE_CHARS = 100_000

FileMode = Literal["read", "write", "append", "list"]


class FileIOError(ValueError):
    """文件操作失败（路径之外的业务错误）。"""


def _entry_line(item: Path) -> str:
    """渲染列表模式里的一行：类型 + 大小 + 相对路径。"""
    try:
        relative = item.relative_to(workspace_root())
    except ValueError:  # pragma: no cover - 已在围栏内，理论上不会发生
        relative = item
    size = item.stat().st_size if item.is_file() else 0
    kind = "dir " if item.is_dir() else "file"
    return f"{kind}  {size:>8}  {relative}"


def file_io(
    path: Annotated[
        str,
        Field(description="相对沙箱工作区的路径，例如 notes/todo.md；不允许 ../ 或绝对路径"),
    ],
    mode: Annotated[
        FileMode,
        Field(description="操作类型：read 读文本 / write 覆盖写 / append 追加 / list 列目录"),
    ] = "read",
    content: Annotated[
        str | None,
        Field(description="write 或 append 时要写入的文本；read / list 时留空"),
    ] = None,
) -> str:
    """在沙箱工作区内读写文本文件，或列出目录内容。"""
    if mode == "read":
        target = resolve_workspace_path(path, must_exist=True)
        if target.is_dir():
            raise FileIOError(f"{path} 是目录，读取请用 mode=list")
        text = target.read_text(encoding="utf-8", errors="replace")
        if len(text) > MAX_READ_CHARS:
            return f"{text[:MAX_READ_CHARS]}\n...（已截断，原文 {len(text)} 字符）"
        return text or "（文件为空）"

    if mode == "list":
        target = resolve_workspace_path(path, must_exist=True)
        if target.is_file():
            return _entry_line(target)
        entries = sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name))
        if not entries:
            return f"{path} 是空目录"
        listing = "\n".join(_entry_line(item) for item in entries)
        return f"{path} 下共 {len(entries)} 项：\n{listing}"

    # write / append
    if content is None:
        raise FileIOError(f"mode={mode} 必须提供 content")
    if len(content) > MAX_WRITE_CHARS:
        raise FileIOError(f"写入内容过长（{len(content)} > {MAX_WRITE_CHARS} 字符）")

    target = resolve_workspace_path(path, for_write=True)
    if target.is_dir():
        raise FileIOError(f"{path} 是目录，不能写入")
    if mode == "write":
        target.write_text(content, encoding="utf-8")
        action = "覆盖写入"
    else:
        with target.open("a", encoding="utf-8") as handle:
            handle.write(content)
        action = "追加写入"
    relative = target.relative_to(workspace_root())
    return f"已{action} {relative}（{len(content)} 字符，当前 {target.stat().st_size} 字节）"


def register(registry: ToolRegistry) -> ToolSpec:
    """把 file_io 注册进给定注册表。"""
    return registry.register(
        file_io,
        name="file_io",
        description=(
            "在沙箱工作区内读写文本文件或列目录。需要落盘中间产物、读取已有资料时使用；"
            "路径必须相对工作区，越界路径会被拒绝"
        ),
        danger_level="high",
        timeout=10,
        retry=1,
    )


__all__ = ["MAX_READ_CHARS", "MAX_WRITE_CHARS", "FileIOError", "file_io", "register"]
