"""Accessibility checks that do not need a browser.

The scripted keyboard and screen-reader journeys run against a built app in the
end-to-end suite. What lives here is everything that can be decided from the
source: contrast ratios in the token palette, focus visibility, reduced-motion
coverage, and the markup rules that a component either follows or does not.

Contrast is computed properly (WCAG 2.x relative luminance), not eyeballed: the
palette is the one place a contrast failure affects every surface at once.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts._paths import PORTAL, REPO_ROOT

TOKENS = PORTAL / "styles" / "tokens"
GLOBALS_CSS = PORTAL / "styles" / "globals.css"

# WCAG 2.2: 4.5:1 for body text, 3:1 for large text and UI components.
BODY_TEXT_RATIO = 4.5
LARGE_TEXT_RATIO = 3.0

HEX = re.compile(r"^#([0-9a-fA-F]{6})$")
DECLARATION = re.compile(r"--([a-z0-9-]+):\s*([^;]+);")


def _load_tokens() -> dict[str, str]:
    """Root-scope token values, with var() references resolved."""
    text = (TOKENS / "colour.css").read_text(encoding="utf-8")
    root = text.split(":root {", maxsplit=1)[1].split("\n}", maxsplit=1)[0]
    raw = {name: value.strip() for name, value in DECLARATION.findall(root)}

    resolved: dict[str, str] = {}
    for _ in range(len(raw)):
        for name, value in raw.items():
            if name in resolved:
                continue
            reference = re.fullmatch(r"var\(--([a-z0-9-]+)\)", value)
            if reference is None:
                resolved[name] = value
            elif reference.group(1) in resolved:
                resolved[name] = resolved[reference.group(1)]
    return resolved


def _channel(value: int) -> float:
    fraction = value / 255
    return fraction / 12.92 if fraction <= 0.03928 else ((fraction + 0.055) / 1.055) ** 2.4


def _luminance(hex_colour: str) -> float:
    match = HEX.match(hex_colour)
    assert match is not None, f"{hex_colour} is not a six-digit hex colour"
    digits = match.group(1)
    red, green, blue = (int(digits[index : index + 2], 16) for index in (0, 2, 4))
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def contrast(foreground: str, background: str) -> float:
    lighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


@pytest.fixture(scope="module")
def tokens() -> dict[str, str]:
    return _load_tokens()


@pytest.mark.parametrize(
    ("foreground", "background", "minimum", "usage"),
    [
        ("text-primary", "surface-page", BODY_TEXT_RATIO, "body copy on the page ground"),
        ("text-primary", "surface-raised", BODY_TEXT_RATIO, "body copy on a card"),
        ("text-secondary", "surface-page", BODY_TEXT_RATIO, "secondary copy on the page"),
        ("text-secondary", "surface-raised", BODY_TEXT_RATIO, "secondary copy on a card"),
        ("text-muted", "surface-page", LARGE_TEXT_RATIO, "labels and counts"),
        ("text-muted", "surface-raised", LARGE_TEXT_RATIO, "labels on a card"),
        ("colour-accent-500", "surface-raised", LARGE_TEXT_RATIO, "links and controls"),
        ("colour-band-unfit", "surface-raised", LARGE_TEXT_RATIO, "the at-risk band"),
        ("colour-band-at-risk", "surface-raised", LARGE_TEXT_RATIO, "the watch band"),
        ("colour-band-exemplary", "surface-raised", LARGE_TEXT_RATIO, "the healthy band"),
        ("colour-status-error", "surface-raised", LARGE_TEXT_RATIO, "error text"),
    ],
)
def test_light_theme_contrast_meets_wcag(
    tokens: dict[str, str], foreground: str, background: str, minimum: float, usage: str
) -> None:
    ratio = contrast(tokens[foreground], tokens[background])

    assert ratio >= minimum, (
        f"{usage}: {foreground} on {background} is {ratio:.2f}:1, below {minimum}:1"
    )


def test_hero_copy_clears_body_contrast_against_the_scrim(tokens: dict[str, str]) -> None:
    """13.3: the constellation sits behind a scrim guaranteeing 4.5:1 for hero copy.

    The scrim is opaque enough that the worst case is the scrim's own base
    colour, so the check is against that rather than against the artwork.
    """
    ratio = contrast(tokens["text-on-hero"], tokens["colour-ink-950"])

    assert ratio >= BODY_TEXT_RATIO


def test_every_semantic_role_is_defined_in_the_light_palette(tokens: dict[str, str]) -> None:
    required = {
        "surface-page", "surface-raised", "surface-sunken", "surface-hero", "border-subtle",
        "border-strong", "text-primary", "text-secondary", "text-muted", "text-on-hero",
        "focus-ring",
    }

    assert required <= set(tokens)


def test_the_dark_theme_redefines_every_role_it_needs_to() -> None:
    """A role defined only in the light block would read as light text on dark."""
    text = (TOKENS / "colour.css").read_text(encoding="utf-8")
    dark = text.split("[data-theme='dark']", maxsplit=1)[1]

    for role in ("surface-page", "surface-raised", "text-primary", "text-secondary", "focus-ring"):
        assert f"--{role}:" in dark, role


def test_focus_is_always_visible() -> None:
    css = GLOBALS_CSS.read_text(encoding="utf-8")

    assert ":focus-visible" in css
    assert "outline:" in css
    assert "outline: none" not in css.replace(" ", " ")


def test_a_skip_link_exists_and_targets_the_main_landmark() -> None:
    layout = (PORTAL / "app" / "layout.tsx").read_text(encoding="utf-8")

    assert 'className="skip-link"' in layout
    assert 'href="#main"' in layout
    assert 'id="main"' in layout
    assert "<main" in layout


def test_reduced_motion_is_honoured_in_the_token_layer() -> None:
    motion = (TOKENS / "motion.css").read_text(encoding="utf-8")

    assert "prefers-reduced-motion: reduce" in motion
    assert "--duration-base: 0ms" in motion


def _components() -> list[Path]:
    return sorted(
        path
        for path in (PORTAL / "components").rglob("*.tsx")
        if path.is_file()
    ) + sorted(
        path for path in (PORTAL / "app").rglob("*.tsx") if path.is_file()
    )


def test_no_component_uses_a_positive_tabindex() -> None:
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _components()
        if re.search(r"tabIndex=\{[1-9]", path.read_text(encoding="utf-8"))
    ]

    assert offenders == []


def test_every_table_declares_a_caption_or_an_accessible_name() -> None:
    offenders: list[str] = []
    for path in _components():
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"<table\b", text):
            window = text[match.start() : match.start() + 2000]
            if "<caption" not in window and "aria-label" not in window:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{text.count(chr(10), 0, match.start()) + 1}")

    assert offenders == []


def test_every_table_header_cell_declares_its_scope() -> None:
    offenders: list[str] = []
    for path in _components():
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"<th\b([^>]*)>", text):
            if "scope=" not in match.group(1):
                offenders.append(str(path.relative_to(REPO_ROOT)))

    assert offenders == []


def test_every_input_has_a_label() -> None:
    offenders: list[str] = []
    for path in _components():
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"<input\b([^>]*)>", text, re.DOTALL):
            attributes = match.group(1)
            identifier = re.search(r'id="([^"]+)"', attributes)
            labelled = (
                "aria-label" in attributes
                or "aria-labelledby" in attributes
                or (identifier and f'htmlFor="{identifier.group(1)}"' in text)
            )
            if not labelled:
                offenders.append(str(path.relative_to(REPO_ROOT)))

    assert offenders == []


def test_every_page_renders_exactly_one_h1() -> None:
    offenders: list[str] = []
    for path in (PORTAL / "app").rglob("page.tsx"):
        text = path.read_text(encoding="utf-8")
        if text.count("<h1") != 1:
            offenders.append(f"{path.relative_to(REPO_ROOT)} has {text.count('<h1')}")

    assert offenders == []


def test_nav_landmarks_are_named() -> None:
    """Two unnamed navs on one page are indistinguishable to a screen reader."""
    offenders: list[str] = []
    for path in _components():
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"<nav\b([^>]*)>", text, re.DOTALL):
            if "aria-label" not in match.group(1) and "aria-labelledby" not in match.group(1):
                offenders.append(str(path.relative_to(REPO_ROOT)))

    assert offenders == []


def test_the_five_component_states_are_available_to_every_surface() -> None:
    """Section 12: loading, empty, error, partial-permission, populated."""
    boundary = (PORTAL / "components" / "ui" / "StateBoundary.tsx").read_text(encoding="utf-8")

    for state in ("LoadingState", "ErrorState", "PermissionNotice", "StateBoundary"):
        assert f"export function {state}" in boundary
    assert "partial_permission" in boundary
    assert "'empty'" in boundary


def test_status_colour_is_never_the_only_signal() -> None:
    """A band is always rendered with its label beside its colour."""
    badge = (PORTAL / "components" / "ui" / "Badge.tsx").read_text(encoding="utf-8")
    ring = (PORTAL / "components" / "ui" / "QualityRing.tsx").read_text(encoding="utf-8")

    assert "{children}" in badge
    # The ring carries its numeric value and an aria-label naming the band.
    assert "quality-ring__value" in ring
    assert "aria-label" in ring


# ---------------------------------------------------------------------------
# M11 acceptance: a keyboard user can pause every moving element, and the
# reduced-motion page carries the same information as the moving one.
# ---------------------------------------------------------------------------

LANDING = PORTAL / "components" / "landing"


def _landing_source(name: str) -> str:
    return (LANDING / name).read_text(encoding="utf-8")


def test_every_band_that_moves_offers_a_visible_pause_control() -> None:
    """WCAG 2.2.2, and the M11 acceptance criterion.

    The ribbon and the theatre both run longer than five seconds, so each needs
    its own control — and there is a global one in the hero for everything at
    once, because a visitor who wants the page to stop should not have to find
    three buttons.
    """
    for name, label in (("ProductRibbon.tsx", "Pause"), ("AnswerTheatre.tsx", "Pause")):
        source = _landing_source(name)
        assert f"{label}" in source
        assert "aria-pressed" in source

    toggle = (PORTAL / "components" / "motion" / "MotionToggle.tsx").read_text(encoding="utf-8")
    assert "aria-pressed" in toggle
    assert "Reduce motion" in toggle


def test_the_pause_controls_are_buttons_rather_than_glyphs() -> None:
    """A control operated by pointer only is not a control for everyone."""
    for name in ("ProductRibbon.tsx", "AnswerTheatre.tsx"):
        source = _landing_source(name)
        assert 'type="button"' in source


def test_the_ribbon_pauses_while_focus_is_inside_it() -> None:
    """13.2: tab moves card to card and motion holds for as long as focus is in.

    Without this a keyboard user is reading a moving target, which is the one
    way a ribbon becomes actively hostile rather than merely decorative.
    """
    source = _landing_source("ProductRibbon.tsx")
    assert "onFocusCapture" in source
    assert "onBlurCapture" in source


def test_the_seam_copy_is_hidden_from_assistive_technology() -> None:
    """The duplicate exists to make a loop seamless, not to be read twice."""
    for name in ("ProductRibbon.tsx", "ActivityTicker.tsx"):
        assert "aria-hidden" in _landing_source(name)


def test_the_constellation_is_decorative_behind_the_copy() -> None:
    """13.3: it never captures scroll, and it is not a landmark to get lost in.

    As the interactive miniature further down the page the same component is
    reachable and labelled; behind the headline it is a backdrop, and a screen
    reader announcing sixty product nodes before the hero copy would be
    announcing the whole catalog before the sentence explaining it.
    """
    source = _landing_source("Constellation.tsx")
    assert "aria-hidden={interactive ? undefined : true}" in source
    assert "pointerEvents: interactive ? 'auto' : 'none'" in source
    # Interactive mode is keyboard-reachable and labelled.
    assert "tabIndex={interactive ? 0 : undefined}" in source
    assert "aria-label={interactive" in source


def test_the_theatre_renders_its_answer_without_javascript() -> None:
    """The completed answer is the server frame, not something that arrives.

    It is also the reduced-motion frame. A visitor who never runs the
    choreography sees the same headline, the same chart and the same rows as
    one who watches it type.
    """
    source = _landing_source("AnswerTheatre.tsx")
    assert "useState<Stage>('hold')" in source
    assert "renderStatic: complete" in source
