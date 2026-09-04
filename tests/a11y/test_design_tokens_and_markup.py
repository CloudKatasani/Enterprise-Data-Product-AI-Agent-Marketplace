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


def _load_tokens(*files: str) -> dict[str, str]:
    """Root-scope token values, with var() references resolved.

    Defaults to the colour file, which is what the contrast tests want. The
    layout tests pass the files they need: space and typography carry the
    reserved heights and the type ramp.
    """
    raw: dict[str, str] = {}
    for name in files or ("colour.css",):
        text = (TOKENS / name).read_text(encoding="utf-8")
        root = text.split(":root {", maxsplit=1)[1].split("\n}", maxsplit=1)[0]
        raw.update({key: value.strip() for key, value in DECLARATION.findall(root)})

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


# ---------------------------------------------------------------------------
# M12.4 — internationalisation, direction and the 35% expansion pass
# ---------------------------------------------------------------------------

# German and Finnish run roughly a third longer than English. A design that fits
# its own copy exactly is a design that breaks on its first translation, and the
# break is a rebuild rather than a retranslation.
EXPANSION = 1.35


def test_direction_is_a_document_attribute_not_a_stylesheet() -> None:
    """Mirroring the whole interface should be one attribute.

    It is one attribute only if every rule is written in logical properties,
    which `npm run lint:logical-properties` enforces. This asserts the other
    half: that the attribute is actually driven by the locale rather than
    hardcoded.
    """
    layout = (PORTAL / "app" / "layout.tsx").read_text(encoding="utf-8")
    assert 'dir={direction}' in layout
    assert 'lang={locale}' in layout
    assert 'dir="ltr"' not in layout

    locale = (PORTAL / "lib" / "locale.ts").read_text(encoding="utf-8")
    for language in ("ar", "he", "fa", "ur"):
        assert f"'{language}'" in locale


def test_no_surface_sizes_itself_to_the_length_of_english() -> None:
    """A fixed width around text is a layout that cannot be translated.

    Text containers are allowed a *max* width — that is a reading measure, and
    prose past about seventy characters costs comprehension in any language. A
    fixed `width` or `height` on something holding a string is the failure: it
    has no room for the same sentence in German.
    """
    css = (PORTAL / "styles" / "globals.css").read_text(encoding="utf-8")
    text_bearing = re.compile(
        r"\.(band-sub|hero-headline|hero-sub|counter-label|proof-label|proof-detail|"
        r"academy-module|module-body|theatre-headline|theatre-narrative|"
        r"incident-headline|incident-detail|how-body)\s*\{([^}]*)\}"
    )
    for match in text_bearing.finditer(css):
        body = match.group(2)
        assert not re.search(r"(?<![-a-z])(width|height)\s*:", body), (
            f".{match.group(1)} fixes its own size; expanded text has nowhere to go"
        )


# Each reserved box and the lines of type it holds, by role. Stated rather than
# inferred: a test that guessed would either compare the ticker against display
# type and fail, or compare the hero against small type and prove nothing.
RESERVED_BOXES = {
    "hero-height": (("text-3xl", 3), ("text-md", 3), ("text-sm", 2)),
    "counter-strip-height": (("text-2xl", 1), ("text-xs", 1)),
    "proof-tile-height": (("text-2xl", 1), ("text-sm", 1), ("text-xs", 2)),
    "ticker-height": (("text-sm", 3),),
}

# Boxes that hold text of unbounded length — a product's name, an agent's
# capability statement — cannot be sized for it in any language. They clamp
# instead, and the clamp is what makes a fixed height honest. This asserts the
# clamp exists rather than pretending the box is big enough.
CLAMPED_BOXES = {
    "card-product-height": ("product-card",),
    "card-agent-height": ("agent-tile",),
    "ribbon-band-height": ("ribbon-list",),
}


def test_every_reserved_box_leaves_room_for_expansion() -> None:
    """The landing bands reserve exact boxes to hold CLS at zero (13.6).

    That pulls against translation: a box tight enough to reserve is a box
    expanded copy overflows. The tension is resolved in the tokens rather than
    discovered in a screenshot — each reserved height is checked against the
    lines of type it holds at 35% expansion.
    """
    tokens = _load_tokens("space.css", "typography.css")
    leading = float(tokens["leading-normal"])

    for box, budget in RESERVED_BOXES.items():
        height = int(tokens[box].rstrip("px"))
        needed = sum(
            int(tokens[role].rstrip("px")) * leading * lines * EXPANSION
            for role, lines in budget
        )
        assert height >= needed, (
            f"--{box} is {height}px; its content at {EXPANSION:.0%} expansion "
            f"needs {needed:.0f}px"
        )


def test_a_box_that_cannot_be_sized_for_translation_clamps_instead() -> None:
    """A fixed height around unbounded text is only honest if it truncates.

    A product name or a capability statement has no length this design can
    promise in every language. The card reserves its box — the grid depends on
    it — and clamps what it holds, so expansion changes what is shown rather
    than where the next card starts.
    """
    css = (PORTAL / "styles" / "globals.css").read_text(encoding="utf-8")
    for box, classes in CLAMPED_BOXES.items():
        assert box in css, f"--{box} is unused"
        for name in classes:
            rule = re.search(rf"\.{re.escape(name)}\s*\{{([^}}]*)\}}", css)
            assert rule is not None, f".{name} has no rule"

    # The clamps themselves. Every one of these is a promise that the layout
    # holds whatever the string turns out to be.
    for clamp in ("line-clamp", "text-overflow", "truncate", "overflow: hidden"):
        assert clamp in css or clamp in _card_markup(), clamp


def _card_markup() -> str:
    return "".join(
        path.read_text(encoding="utf-8")
        for path in (PORTAL / "components").rglob("*.tsx")
    )


def test_prose_is_measured_in_characters_not_pixels() -> None:
    """A measure in `ch` expands with the type; a measure in pixels does not."""
    tokens = _load_tokens("space.css")
    assert tokens["measure-prose"].endswith("ch")
    assert tokens["measure-chip"].endswith("ch")


def test_no_string_is_assembled_from_fragments_in_a_component() -> None:
    """Concatenated sentence fragments cannot be translated.

    "N of M " + noun reads fine in English and is unorderable in a language that
    puts the noun first. Counts go through `count()`, which takes both forms of
    the noun; anything else is a sentence a translator would have to reverse
    engineer.
    """
    units = (PORTAL / "lib" / "units.ts").read_text(encoding="utf-8")
    assert "export function count(" in units
    assert "singular" in units and "plural" in units
