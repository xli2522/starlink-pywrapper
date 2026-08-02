"""Parse the brace-based Starlink IFD format used by current source trees."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
import re
from typing import Iterator


_ACTION = re.compile(r"(?im)^[ \t]*action[ \t]+([A-Za-z0-9_]+)[ \t]*\{")
_PARAMETER = re.compile(
    r"(?im)^[ \t]*parameter[ \t]+([A-Za-z0-9_]+)[ \t]*\{"
)
_FIELD = re.compile(
    r"^[ \t]*(type|ptype|prompt|default|position|range|in|access|association|"
    r"ppath|vpath|size)[ \t]+(.+?)[ \t]*$",
    re.IGNORECASE,
)


class IfdParseError(ValueError):
    """Raised when pinned source metadata is malformed or ambiguous."""


def _balanced_body(text: str, opening_brace: int, source: Path) -> tuple[str, int]:
    depth = 0
    for index in range(opening_brace, len(text)):
        character = text[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return text[opening_brace + 1:index], index + 1
    raise IfdParseError(f"Unterminated brace block in {source}")


def _named_blocks(
    text: str, pattern: re.Pattern[str], source: Path
) -> Iterator[tuple[str, str]]:
    cursor = 0
    while True:
        match = pattern.search(text, cursor)
        if match is None:
            return
        opening = text.find("{", match.start(), match.end())
        body, cursor = _balanced_body(text, opening, source)
        yield match.group(1).lower(), body


def _clean_value(value: str) -> str:
    value = value.strip()
    if value.startswith("{") and value.endswith("}"):
        value = value[1:-1].strip()
    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in {"'", '"'}
    ):
        value = value[1:-1]
    return value


def _parse_parameter(body: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in body.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        match = _FIELD.match(line)
        if match:
            key = match.group(1).lower()
            result[key] = _clean_value(match.group(2))
    return result


def parse_ifd_actions(path: Path) -> dict[str, OrderedDict[str, dict[str, str]]]:
    """Return ordered action/parameter metadata from one IFD file."""

    source = Path(path)
    text = source.read_text(encoding="utf-8", errors="replace")
    actions: dict[str, OrderedDict[str, dict[str, str]]] = {}
    for action_name, action_body in _named_blocks(text, _ACTION, source):
        parameters: OrderedDict[str, dict[str, str]] = OrderedDict()
        for parameter_name, parameter_body in _named_blocks(
            action_body, _PARAMETER, source
        ):
            if parameter_name in parameters:
                raise IfdParseError(
                    f"Duplicate parameter {action_name}.{parameter_name} in {source}"
                )
            parameters[parameter_name] = _parse_parameter(parameter_body)
        if action_name in actions and actions[action_name] != parameters:
            raise IfdParseError(f"Conflicting action {action_name} in {source}")
        actions[action_name] = parameters
    return actions


def load_ifd_tree(root: Path) -> dict[str, OrderedDict[str, dict[str, str]]]:
    """Load every IFD/IFD.IN below a package root with conflict checking."""

    actions: dict[str, OrderedDict[str, dict[str, str]]] = {}
    primary = sorted(Path(root).rglob("*.ifd.in"))
    secondary = sorted(Path(root).rglob("*.ifd"))
    paths = primary + secondary
    for path in paths:
        for name, parameters in parse_ifd_actions(path).items():
            previous = actions.get(name)
            if previous is not None:
                # IFD.IN is the maintained package source; later duplicate
                # monitor IFDs are generated subsets and are ignored.
                continue
            actions[name] = parameters
    return actions
