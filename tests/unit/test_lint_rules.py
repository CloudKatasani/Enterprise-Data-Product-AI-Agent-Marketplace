"""M0 acceptance — the rules of engagement are enforced by CI, not by review.

Each test plants a deliberate violation in a temporary tree and asserts the lint
rule reports it, then asserts the compliant form is accepted.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))


@pytest.fixture()
def magic_numbers(monkeypatch, tmp_path: Path):
    module = importlib.import_module("lint.no_magic_numbers")
    services = tmp_path / "services"
    portal = tmp_path / "portal"
    services.mkdir()
    portal.mkdir()
    monkeypatch.setattr(module, "PY_ROOTS", [services])
    monkeypatch.setattr(module, "TS_ROOT", portal)
    monkeypatch.setattr(module, "PY_EXEMPT_FILES", set())
    monkeypatch.setattr(module, "TS_EXEMPT_PREFIXES", ())
    return module, services, portal


def test_hardcoded_threshold_in_python_fails(magic_numbers) -> None:
    module, services, _ = magic_numbers
    (services / "scoring.py").write_text("def gate(score):\n    return score >= 0.75\n")

    findings = module.scan_python()

    assert len(findings) == 1
    assert "0.75" in findings[0].message
    assert "manifests/rubrics/" in findings[0].message


def test_rubric_resolved_threshold_in_python_passes(magic_numbers) -> None:
    module, services, _ = magic_numbers
    (services / "scoring.py").write_text(
        "def gate(score, rubric):\n"
        "    return score >= rubric.threshold('duplicate_detection.blocking_threshold')\n"
    )

    assert module.scan_python() == []


def test_allowed_identity_values_pass(magic_numbers) -> None:
    module, services, _ = magic_numbers
    (services / "util.py").write_text(
        "def normalise(values):\n"
        "    if not values:\n"
        "        return 0\n"
        "    return values[0] + 1 - 1\n"
    )

    assert module.scan_python() == []


def test_subscript_index_is_not_a_magic_number(magic_numbers) -> None:
    module, services, _ = magic_numbers
    (services / "util.py").write_text("def third(values):\n    return values[2]\n")

    assert module.scan_python() == []


def test_hardcoded_threshold_in_portal_fails(magic_numbers) -> None:
    module, _, portal = magic_numbers
    (portal / "ribbon.tsx").write_text("export const cards = all.slice(0, 12);\n")

    findings = module.scan_typescript()

    assert any("12" in finding.message for finding in findings)


def test_numbers_inside_strings_and_comments_are_ignored(magic_numbers) -> None:
    module, _, portal = magic_numbers
    (portal / "copy.tsx").write_text(
        "// budget is 58fps\nexport const label = 'p95 is 400ms';\n"
    )

    assert module.scan_typescript() == []


def test_brand_string_fails(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("lint.no_brand_strings")
    portal = tmp_path / "portal"
    portal.mkdir()
    (portal / "hero.tsx").write_text("export const title = 'Welcome to Acme Data Exchange';\n")
    monkeypatch.setattr(module, "SCAN_ROOTS", [portal])
    monkeypatch.setattr(module, "TOKEN_DIR", tmp_path / "tokens")

    findings = list(_collect_brand(module))

    assert any("brand string" in f.message for f in findings)


def test_raw_hex_outside_tokens_fails(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("lint.no_brand_strings")
    portal = tmp_path / "portal"
    portal.mkdir()
    (portal / "card.tsx").write_text("const border = '#1d2434';\n")
    monkeypatch.setattr(module, "SCAN_ROOTS", [portal])
    monkeypatch.setattr(module, "TOKEN_DIR", tmp_path / "tokens")

    findings = _collect_brand(module)

    assert any("raw hex colour" in f.message for f in findings)


def _collect_brand(module) -> list:
    import io
    from contextlib import redirect_stderr, redirect_stdout

    captured: list = []
    original_report = module.report

    def capture(rule: str, findings: list) -> int:
        captured.extend(findings)
        return original_report(rule, findings)

    module.report = capture
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            module.main()
    finally:
        module.report = original_report
    return captured


def test_animating_width_fails(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("lint.animatable_props")
    portal = tmp_path / "portal"
    portal.mkdir()
    (portal / "ribbon.css").write_text(".card { transition: width 240ms ease; }\n")
    monkeypatch.setattr(module, "PORTAL", portal)

    findings = module.scan_css()

    assert any("width" in f.message for f in findings)


def test_animating_transform_passes(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("lint.animatable_props")
    portal = tmp_path / "portal"
    portal.mkdir()
    (portal / "ribbon.css").write_text(
        ".card { transition: transform var(--duration-base) var(--ease-standard); }\n"
    )
    monkeypatch.setattr(module, "PORTAL", portal)

    assert module.scan_css() == []


def test_web_animations_forbidden_property_fails(monkeypatch, tmp_path: Path) -> None:
    module = importlib.import_module("lint.animatable_props")
    portal = tmp_path / "portal"
    portal.mkdir()
    (portal / "pulse.ts").write_text(
        "el.animate([{ boxShadow: 'none' }, { boxShadow: 'x' }], options);\n"
    )
    monkeypatch.setattr(module, "PORTAL", portal)

    findings = module.scan_ts()

    assert any("boxShadow" in f.message for f in findings)
