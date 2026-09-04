"""M2 acceptance — hand-editing a generated file fails the build (rule 3)."""

from __future__ import annotations

import io
import shutil
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

import scripts.lint.generated as rule
from scripts._paths import GENERATED


@pytest.fixture()
def sandbox(tmp_path: Path, monkeypatch) -> Path:
    generated = tmp_path / "generated"
    shutil.copytree(GENERATED, generated)
    monkeypatch.setattr(rule, "GENERATED", generated)
    monkeypatch.setattr(rule, "REPO_ROOT", tmp_path)
    return generated


def _run() -> tuple[int, str]:
    stderr = io.StringIO()
    with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
        code = rule.main()
    return code, stderr.getvalue()


def test_the_committed_tree_is_clean(sandbox: Path) -> None:
    code, _ = _run()

    assert code == 0


def test_editing_a_generated_sql_file_is_caught(sandbox: Path) -> None:
    target = sandbox / "ddl" / "0004_supply_data.sql"
    text = target.read_text(encoding="utf-8")
    target.write_text(text.replace("known_limitations TEXT NOT NULL", "known_limitations TEXT"))

    code, output = _run()

    assert code == 1
    assert "0004_supply_data.sql" in output
    assert "run npm run gen" in output


def test_stripping_the_header_is_caught(sandbox: Path) -> None:
    target = sandbox / "types" / "enums.ts"
    lines = target.read_text(encoding="utf-8").splitlines()
    target.write_text("\n".join(lines[3:]), encoding="utf-8")

    code, output = _run()

    assert code == 1
    assert "carries no auto-generated header" in output


def test_adding_a_file_nothing_generates_is_caught(sandbox: Path) -> None:
    (sandbox / "ddl" / "9999_hand_written.sql").write_text(
        "-- AUTO-GENERATED FROM nowhere BY scripts/gen.py\n"
        "-- generator_version: 1.0.0  manifest_hash: " + "e" * 64 + "  generated_at: x\n\n"
        "SELECT 1;\n",
        encoding="utf-8",
    )

    code, output = _run()

    assert code == 1
    assert "not produced by any generator" in output


def test_deleting_a_generated_file_is_caught(sandbox: Path) -> None:
    (sandbox / "mcp" / "DP-TEL-001.json").unlink()

    code, output = _run()

    assert code == 1
    assert "not committed" in output
