#!/usr/bin/env python
"""极简 PDF 生成器：纯手写 PDF 语法产出文本型多页文档。

用途：``scripts/bench_index.py``（50 页基准）与 rag 测试夹具共用。
刻意不引入 reportlab（AGPL 体积大、且 bench 只需要 ASCII 文本流）。

产出的 PDF 结构（合法但极简）::

    %PDF-1.4
    1 0 obj Catalog / 2 0 obj Pages / 3..N+2 obj Page(+Contents) / 尾obj xref

文本用 Helvetica（WinAnsi），**仅支持 ASCII**——中文测试样例请用 MD/DOCX。
"""

from __future__ import annotations

from pathlib import Path


def _escape(text: str) -> str:
    """PDF 字符串转义（\\ ( ) 与非 ASCII 替换）。"""
    cleaned = text.encode("ascii", "replace").decode("ascii")
    return cleaned.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def write_pdf(
    path: str | Path,
    pages: list[list[str]],
    *,
    page_width: int = 612,
    page_height: int = 792,
    body_size: int = 11,
    heading_size: int = 16,
) -> Path:
    """把 ``pages[页号][行号]`` 写成文本型 PDF。

    Args:
        path: 输出路径（父目录自动创建）。
        pages: 每页的行列表；空行跳过。
        body_size: 正文字号；heading_size: 标题字号（``"# "`` 开头的行）。

    Returns:
        写入的路径（供调用方链式使用）。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    objects: list[bytes] = []  # 编号从 1 起，按 append 顺序
    page_obj_ids: list[int] = []

    # 预留 1:Catalog 2:Pages；每页占 3 个对象：Page / Contents / Font? 字体共用一个
    font_obj_no = 3
    first_page_obj = font_obj_no + 1

    def add_object(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font_id = None  # 延后分配（对象编号必须严格递增追加）

    # 先追加 Page/Contents，最后追加 Font（编号顺序不重要，xref 决定一切）
    for page_lines in pages:
        # 每行独立定位（Tm）；空行只下移行距
        stream_lines: list[str] = ["BT"]
        y = page_height - 72
        for line in page_lines:
            if not line.strip():
                y -= body_size * 1.2
                continue
            if line.startswith("# "):
                size, text = heading_size, line[2:]
            else:
                size, text = body_size, line
            stream_lines.append(f"/F1 {size} Tf")
            stream_lines.append(f"1 0 0 1 54 {y} Tm")
            stream_lines.append(f"({_escape(text)}) Tj")
            y -= int(size * 1.6)
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode("latin-1", "replace")

        contents_id = add_object(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
        page_id = add_object(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
            b"/Contents %d 0 R /Resources << /Font << /F1 FONTID 0 R >> >> >>"
            % (page_width, page_height, contents_id)
        )
        page_obj_ids.append(page_id)

    font_id = add_object(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    # 把 Page 对象里的 FONTID 占位替换成真实字体编号
    objects = [
        body.replace(b"FONTID 0 R", f"{font_id} 0 R".encode()) for body in objects
    ]

    catalog_id = add_object(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{pid} 0 R" for pid in page_obj_ids)
    pages_id = add_object(
        b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids.encode(), len(page_obj_ids))
    )

    # 重新排列：Catalog=1, Pages=2, 其余顺延——为简单起见直接按追加顺序输出 xref
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % index + body + b"\nendobj\n"
    xref_at = len(out)
    count = len(objects) + 1
    out += b"xref\n0 %d\n" % count
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += (
        b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (count, catalog_id, xref_at)
    )
    path.write_bytes(bytes(out))
    return path


__all__ = ["write_pdf"]
