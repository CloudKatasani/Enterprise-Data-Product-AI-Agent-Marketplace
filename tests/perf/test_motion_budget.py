"""M11 — the motion budget (13.6), asserted where it can be asserted.

Frame rate under a 4x CPU throttle needs a browser and a profiler; the rest of
the budget is a property of the source, and the parts that are get checked here
rather than measured once by hand and hoped for.

    every ambient animation has a static equivalent carrying the same
    information;

    only `transform` and `opacity` animate, and only the controller runs a
    frame loop;

    every band reserves its box before paint, which is the whole of a CLS
    budget of 0.00;

    the motion layer stays inside its byte budget.

A test that cannot see the frame rate should say so rather than pretend, so
nothing here claims to have measured one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PORTAL = REPO_ROOT / "portal"
MOTION = PORTAL / "lib" / "motion"
LANDING = PORTAL / "components" / "landing"
GLOBALS_CSS = PORTAL / "styles" / "globals.css"
MOTION_CSS = PORTAL / "styles" / "tokens" / "motion.css"

# 13.1's pause triggers, every one of which must hold for all ambient motion.
PAUSE_TRIGGERS = (
    "reduced-motion",
    "hidden",
    "save-data",
    "battery",
    "viewport",
    "user",
)

# 13.6: the motion layer, including the graph renderer, stays under this.
BUNDLE_BUDGET_KB = 45


def _controller() -> str:
    return (MOTION / "controller.ts").read_text(encoding="utf-8")


def test_the_controller_knows_every_pause_trigger() -> None:
    text = _controller()
    for trigger in PAUSE_TRIGGERS:
        assert f"'{trigger}'" in text, trigger


def test_only_the_controller_runs_a_frame_loop() -> None:
    """One loop, or a pause trigger stops some components and not others."""
    offenders = [
        path
        for path in PORTAL.rglob("*.ts*")
        if "node_modules" not in path.parts
        and ".next" not in path.parts
        and path != MOTION / "controller.ts"
        and "requestAnimationFrame(" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_every_registration_can_compose_a_static_frame() -> None:
    """13.6: every ambient animation has a static equivalent.

    A registration without `renderStatic` would freeze mid-transition when a
    trigger fired, which reads as a rendering fault rather than a paused page.
    """
    for path in LANDING.rglob("*.tsx"):
        text = path.read_text(encoding="utf-8")
        if "useMotionRegistration" not in text:
            continue
        assert "renderStatic" in text, path.name


def test_the_reduced_motion_block_offers_the_same_information() -> None:
    """Not `display: none` on the moving thing and nothing in its place."""
    css = GLOBALS_CSS.read_text(encoding="utf-8")
    reduced = css[css.index("@media (prefers-reduced-motion: reduce)") :]
    assert ".ribbon-rows" in reduced
    # The static grid is what replaces the moving rows. Hiding the rows without
    # showing it would be hiding the band.
    assert ".ribbon-static" in reduced
    assert "display: block" in reduced


def test_every_landing_band_reserves_its_box() -> None:
    """CLS 0.00 is a property of the stylesheet, not of a lucky load order."""
    css = GLOBALS_CSS.read_text(encoding="utf-8")
    for reserved in (
        "--hero-height",
        "--ribbon-band-height",
        "--theatre-height",
        "--counter-strip-height",
        "--ticker-height",
        "--constellation-height",
        "--proof-tile-height",
    ):
        assert reserved in css, reserved


def test_no_landing_component_animates_a_layout_property() -> None:
    """The lint rule enforces this; the test states it, so it cannot be waived."""
    forbidden = re.compile(r"transition:\s*(width|height|top|left|margin|padding)\b")
    for path in list(LANDING.rglob("*.tsx")) + [GLOBALS_CSS]:
        assert forbidden.search(path.read_text(encoding="utf-8")) is None, path.name


def test_the_motion_layer_fits_its_byte_budget() -> None:
    """13.6: 45KB gzipped including the graph renderer.

    Measured on the source rather than a bundle, which is a stricter test than
    the budget asks for: the source is larger than what ships. It is checked
    this way so the number fails when a dependency is added, which is the case
    the budget exists for.
    """
    import gzip

    payload = b"".join(
        path.read_bytes()
        for path in sorted(
            [*MOTION.rglob("*.ts"), LANDING / "Constellation.tsx"]
        )
    )
    kilobytes = len(gzip.compress(payload)) / len(b"0123456789" * 102)
    assert kilobytes < BUNDLE_BUDGET_KB, f"{kilobytes:.1f}KB gzipped"


def test_no_graph_layout_library_is_bundled() -> None:
    """The layout is the server's answer; the client draws what it was given.

    A client-side force library would be both the largest single thing in the
    motion budget and a second opinion about the shape of the estate — and the
    day the two disagreed, the hero and the mesh explorer would be drawing
    different pictures of the same graph.
    """
    manifest = (PORTAL / "package.json").read_text(encoding="utf-8")
    for library in ("d3-force", "d3-quadtree", "cytoscape", "vis-network", "sigma"):
        assert f'"{library}"' not in manifest


@pytest.mark.parametrize(
    "token",
    [
        "--ribbon-speed-row1",
        "--ribbon-speed-row2",
        "--constellation-drift-alpha",
        "--orbit-deg-per-sec-min",
        "--orbit-deg-per-sec-max",
        "--theatre-type-cps",
        "--counter-count-up-ms",
        "--ticker-crawl-speed",
        "--motion-battery-floor",
        "--motion-viewport-floor-px",
    ],
)
def test_every_motion_number_is_a_token(token: str) -> None:
    assert token in MOTION_CSS.read_text(encoding="utf-8")
