"""Convert the simple HTML emitted by Starlink ``prohtml`` to RST.

This is a Python 3 implementation of the small conversion model used by
``html2rest`` 0.2.2.  That project is Python-2-only; keeping the supported
tag handling here makes wrapper generation reproducible on Python 3.12.

The original converter is copyright (c) 2006-2011 Gerard Flanagan and was
released under the MIT licence.  This implementation retains that notice and
permission:

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

from html.parser import HTMLParser
from io import StringIO
from textwrap import TextWrapper


_CODE_BLOCK = "::"
_IGNORED_TAGS = {"script", "style", "title"}
_UNDERLINES = "#-~`+;"


class _LineBuffer:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.wrapper = TextWrapper()

    def __bool__(self) -> bool:
        return bool(self.lines)

    def clear(self) -> None:
        self.lines.clear()

    def read(self) -> str:
        return "\n".join(self.lines)

    def write(self, text: str) -> None:
        normalized = " ".join(text.split())
        if normalized:
            self.lines.extend(self.wrapper.wrap(normalized))

    def raw_write(self, text: str) -> None:
        self.lines.extend(text.splitlines())

    def indent(self, spaces: int = 4, start: int = 0) -> None:
        prefix = " " * spaces
        for index in range(start, len(self.lines)):
            self.lines[index] = prefix + self.lines[index]

    def lstrip(self) -> None:
        self.lines[:] = [line.lstrip() for line in self.lines]


class _Renderer(HTMLParser):
    """Render the deliberately small tag set produced by ``prohtml``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output = StringIO()
        self.text = StringIO()
        self.lines = _LineBuffer()
        self.verbatim = False
        self.lists: list[str] = []
        self.ignored_depth = 0
        self.block_depth = 0
        self.links: dict[str, str] = {}
        self.pending_link: str | None = None

    def result(self) -> str:
        self._write_line()
        value = self.output.getvalue().replace("\r\n", "\n")
        return value.strip() + "\n"

    def _clear_text(self) -> None:
        self.text.seek(0)
        self.text.truncate()

    def _flush_text(self) -> None:
        value = self.text.getvalue()
        if not value:
            return
        if self.lines:
            self.lines.lines[-1] += value
        else:
            self.lines.write(value)
        self._clear_text()

    def _flush(self) -> None:
        if not self.lines:
            return
        if self.block_depth > 1:
            self.lines.indent(4 * (self.block_depth - 1))
        self.output.write(self.lines.read())
        self.lines.clear()

    def _write(self, text: str = "") -> None:
        self._flush_text()
        self._flush()
        self.output.write(text)

    def _write_line(self, text: str = "") -> None:
        self._write(text + "\n")

    def _start_block(self, text: str = "") -> None:
        if self.text.tell() or self.lines:
            self._write_line()
        self._write_line()
        self._write_line(text)

    def _end_block(self, text: str = "") -> None:
        self._write_line(text)
        self._write_line()

    def _block(self, text: str = "") -> None:
        self._start_block(text)
        self._write_line()

    def _data(self, text: str) -> None:
        self.text.write(text)

    def handle_data(self, data: str) -> None:
        if self.ignored_depth:
            return
        if self.verbatim:
            self._data(data)
            return
        normalized = " ".join(data.splitlines())
        if self.pending_link is not None:
            label = " ".join(normalized.split())
            if label:
                self.links[self.pending_link] = label
        self._data(normalized)

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in _IGNORED_TAGS:
            self.ignored_depth += 1
            return
        method = getattr(self, f"_start_{tag}", None)
        if method is not None:
            method(attrs)
        elif len(tag) == 2 and tag[0] == "h" and tag[1].isdigit():
            self._start_block()
        elif tag == "br":
            if self.verbatim:
                self._data("\n")
            elif self.block_depth:
                self._data(" ")
            else:
                self._write_line()
        elif not self.verbatim:
            self._data(" ")

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _IGNORED_TAGS:
            self.ignored_depth = max(0, self.ignored_depth - 1)
            return
        method = getattr(self, f"_end_{tag}", None)
        if method is not None:
            method()
        elif len(tag) == 2 and tag[0] == "h" and tag[1].isdigit():
            self._flush_text()
            if self.lines:
                self.lines.lines[-1] = self.lines.lines[-1].strip()
                level = min(int(tag[1]), len(_UNDERLINES)) - 1
                self.lines.write(_UNDERLINES[level] * len(self.lines.lines[-1]))
                self._write_line()
        elif not self.verbatim:
            self._data(" ")

    def _start_a(self, attrs) -> None:
        href = dict(attrs).get("href")
        if not href or href.startswith("#"):
            return
        self._data("`")
        self.pending_link = href

    def _end_a(self) -> None:
        if self.pending_link is not None:
            self._data("`_")
            self.pending_link = None

    def _start_pre(self, _attrs) -> None:
        if self.lists:
            self._end_li()
            self._write_line()
        self.verbatim = True
        self._block(_CODE_BLOCK)

    def _end_pre(self) -> None:
        value = self.text.getvalue()
        if value:
            self.lines.raw_write(value)
            self.lines.indent(4)
        self._clear_text()
        self._end_block()
        self.verbatim = False

    def _start_ul(self, _attrs) -> None:
        self._start_list("+ ")

    def _end_ul(self) -> None:
        self._end_list()

    def _start_ol(self, _attrs) -> None:
        self._start_list("#. ")

    def _end_ol(self) -> None:
        self._end_list()

    def _start_list(self, marker: str) -> None:
        if self.lists:
            self._end_li()
        self._write_line()
        self.lists.append(marker)
        self.block_depth += 1

    def _end_list(self) -> None:
        self._end_li()
        self.lists.pop()
        self.block_depth -= 1
        if self.block_depth:
            self._write_line()
        else:
            self._end_block()

    def _start_li(self, _attrs) -> None:
        self._write_line()
        self._data(self.lists[-1])

    def _end_li(self) -> None:
        self._flush_text()
        marker = self.lists[-1]
        start = 1 if self.lines and self.lines.lines[0].lstrip().startswith(marker) else 0
        self.lines.indent(len(marker), start=start)
        self._write()

    def _start_p(self, _attrs) -> None:
        if self.verbatim or not self.block_depth:
            self._write_line()

    def _end_p(self) -> None:
        if self.block_depth and not self.verbatim:
            return
        if self.verbatim:
            self._write_line()
        else:
            self.lines.lstrip()
            self._write_line()

    def _start_i(self, _attrs) -> None:
        self._data(" *")

    _start_em = _start_i

    def _end_i(self) -> None:
        self._data("*")

    _end_em = _end_i

    def _start_b(self, _attrs) -> None:
        self._data(" **")

    _start_strong = _start_b

    def _end_b(self) -> None:
        self._data("**")

    _end_strong = _end_b

    def _start_code(self, _attrs) -> None:
        self._data(" ``")

    _start_tt = _start_code

    def _end_code(self) -> None:
        self._data("``")

    _end_tt = _end_code

    def close(self) -> None:
        super().close()
        for href, label in sorted(self.links.items(), key=lambda item: item[1]):
            self._write_line(f".. _{label}: {href}")


def html_to_rst(html: str) -> str:
    """Return deterministic RST for a Starlink ``prohtml`` fragment."""

    renderer = _Renderer()
    renderer.feed(html)
    renderer.close()
    return renderer.result()
