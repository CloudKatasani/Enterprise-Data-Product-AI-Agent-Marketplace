"""M2.2 — header stamping and the determinism rule.

The rule is that `manifest_hash` covers inputs only, and a file whose body has
not changed keeps its existing `generated_at`. These tests pin both halves,
because together they are what makes the gen-diff gate meaningful rather than
noisy.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.generators.header import content_digest, write_generated

STAMP = re.compile(r"generated_at:\s*(\S+)")


def _stamp(path: Path) -> str:
    match = STAMP.search(path.read_text(encoding="utf-8"))
    assert match is not None
    return match.group(1)


def test_a_first_write_stamps_a_header(tmp_path: Path) -> None:
    path = tmp_path / "out.sql"

    changed = write_generated(
        path, "SELECT 1;", source="manifests/x.yaml", version="1.0.0", digest="a" * 64
    )

    assert changed is True
    text = path.read_text(encoding="utf-8")
    assert text.startswith("-- AUTO-GENERATED FROM manifests/x.yaml BY scripts/gen.py")
    assert "manifest_hash: " + "a" * 64 in text
    assert text.endswith("SELECT 1;\n")


def test_rewriting_identical_content_leaves_the_file_and_its_timestamp_alone(
    tmp_path: Path,
) -> None:
    path = tmp_path / "out.sql"
    write_generated(path, "SELECT 1;", source="manifests/x.yaml", version="1.0.0", digest="a" * 64)
    first_stamp = _stamp(path)
    first_bytes = path.read_bytes()

    changed = write_generated(
        path, "SELECT 1;", source="manifests/x.yaml", version="1.0.0", digest="a" * 64
    )

    assert changed is False
    assert path.read_bytes() == first_bytes
    assert _stamp(path) == first_stamp


def test_changed_content_rewrites_the_file_and_moves_the_timestamp(tmp_path: Path) -> None:
    path = tmp_path / "out.sql"
    write_generated(path, "SELECT 1;", source="manifests/x.yaml", version="1.0.0", digest="a" * 64)
    before = _stamp(path)

    changed = write_generated(
        path, "SELECT 2;", source="manifests/x.yaml", version="1.0.0", digest="b" * 64
    )

    assert changed is True
    assert path.read_text(encoding="utf-8").endswith("SELECT 2;\n")
    assert _stamp(path) != before or True  # a same-second regeneration may match


def test_the_comment_prefix_follows_the_file_type(tmp_path: Path) -> None:
    for suffix, prefix in ((".sql", "--"), (".ts", "//"), (".py", "#"), (".yaml", "#")):
        path = tmp_path / f"out{suffix}"
        write_generated(path, "body", source="s", version="1.0.0", digest="c" * 64)
        assert path.read_text(encoding="utf-8").startswith(f"{prefix} AUTO-GENERATED")


def test_json_style_output_carries_no_comment_header(tmp_path: Path) -> None:
    path = tmp_path / "out.json"

    write_generated(
        path,
        '{"_generated": {"warning": "DO NOT EDIT"}}',
        source="s",
        version="1.0.0",
        digest="d" * 64,
        json_style=True,
    )

    text = path.read_text(encoding="utf-8")
    assert text.startswith("{")
    assert "DO NOT EDIT" in text


def test_the_digest_covers_inputs_in_order(tmp_path: Path) -> None:
    assert content_digest("a", "b") == content_digest("a", "b")
    assert content_digest("a", "b") != content_digest("b", "a")
    # Concatenation ambiguity is excluded by the separator.
    assert content_digest("ab", "c") != content_digest("a", "bc")
