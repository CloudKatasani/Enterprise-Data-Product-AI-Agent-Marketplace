"""YAML loading that remembers where every value came from.

M1.2 requires manifest validation to report "precise error messages and line
numbers". ``jsonschema`` reports a JSON pointer into the parsed document, so the
missing half is a map from pointer to source position. This loader builds one by
recording node marks as PyYAML constructs the document.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Position:
    line: int
    column: int

    def render(self) -> str:
        return f"{self.line}:{self.column}"


class LoadError(Exception):
    """A manifest that is not well-formed YAML at all."""

    def __init__(self, path: Path, message: str, position: Position | None) -> None:
        self.path = path
        self.position = position
        super().__init__(message)


@dataclass
class LoadedManifest:
    path: Path
    data: Any
    positions: dict[str, Position]
    text: str

    def position_of(self, pointer: str) -> Position | None:
        """Position of a JSON pointer, falling back to the nearest declared ancestor."""
        candidate = pointer
        while True:
            if candidate in self.positions:
                return self.positions[candidate]
            if not candidate:
                return None
            candidate = candidate.rsplit("/", maxsplit=1)[0]

    def line_of(self, pointer: str) -> int:
        position = self.position_of(pointer)
        return position.line if position else 1

    def source_line(self, line: int) -> str:
        lines = self.text.splitlines()
        index = line - 1
        if 0 <= index < len(lines):
            return lines[index]
        return ""


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


class _PositionalLoader(yaml.SafeLoader):
    """SafeLoader that records the source position of every constructed node.

    Timestamp resolution is disabled: a manifest is text, and JSON Schema
    validates ``dated: 2026-06-01`` as a date-formatted *string*. Letting PyYAML
    build a ``datetime.date`` would make the schema reject its own examples.
    """

    def __init__(self, stream: Any) -> None:
        super().__init__(stream)
        self.positions: dict[str, Position] = {}

    def construct_document(self, node: yaml.Node) -> Any:
        self._record(node, "")
        return super().construct_document(node)

    def _record(self, node: yaml.Node, pointer: str) -> None:
        self.positions[pointer] = Position(node.start_mark.line + 1, node.start_mark.column + 1)
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                key = str(key_node.value)
                self._record(value_node, f"{pointer}/{_escape(key)}")
        elif isinstance(node, yaml.SequenceNode):
            for index, item in enumerate(node.value):
                self._record(item, f"{pointer}/{index}")


_PositionalLoader.yaml_implicit_resolvers = {
    key: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def load_manifest(path: Path) -> LoadedManifest:
    text = path.read_text(encoding="utf-8")
    loader = _PositionalLoader(text)
    try:
        node = loader.get_single_node()
        if node is None:
            raise LoadError(path, "manifest is empty", None)
        loader._record(node, "")
        data = loader.construct_document(node)
    except yaml.MarkedYAMLError as error:
        mark = error.problem_mark
        position = Position(mark.line + 1, mark.column + 1) if mark else None
        raise LoadError(path, error.problem or "invalid YAML", position) from error
    finally:
        loader.dispose()
    return LoadedManifest(path=path, data=data, positions=loader.positions, text=text)
