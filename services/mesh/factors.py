"""The signals both meshes are built from.

Each factor is a number in [0, 1] with a sentence attached. The sentence is not
decoration: I6 requires every rendered edge to carry a rationale, and an edge
whose rationale is "strength 0.42" explains nothing. What a reader needs is
*which* signal put two things next to each other, because that is what tells
them whether the edge is telling them something they can act on.

Confidence is kept separate from strength throughout, and the distinction is
load-bearing. Strength says how related two assets look. Confidence says how
much evidence the comparison had. Two products with one column name in common
and nothing else can score a plausible strength on thin evidence; the rubric's
floor is what stops that being rendered as fact.
"""

from __future__ import annotations

from dataclasses import dataclass

ZERO = 0.0
ONE = 1.0


ONE_ITEM = 1


@dataclass(frozen=True)
class Noun:
    """What the shared things are called, in both numbers.

    A rationale reading "share 1 entity keys" is the kind of small wrongness
    that makes a reader stop trusting the rest of the sentence.
    """

    singular: str
    plural: str


@dataclass(frozen=True)
class Factor:
    """One signal, its value, and how it is explained."""

    code: str
    value: float
    # How much of the possible evidence this signal actually had. A Jaccard over
    # two empty sets is not zero-similarity, it is no information.
    evidence: float
    detail: str


def jaccard(left: set[str], right: set[str]) -> float:
    """Symmetric overlap. Right where neither side is the "asked for" one.

    Used for mesh edges rather than the containment measure the duplicate check
    uses, and deliberately: a mesh edge is a claim that two assets are alike,
    and alike is symmetric. "A covers B" is a different claim and would draw a
    different graph.
    """
    if not left or not right:
        return ZERO
    return len(left & right) / len(left | right)


def overlap_factor(
    code: str,
    left: set[str],
    right: set[str],
    *,
    noun: Noun,
    names: tuple[str, str],
    listed_items: int,
) -> Factor:
    shared = sorted(left & right)
    value = jaccard(left, right)
    evidence = ONE if left and right else ZERO
    if not shared:
        detail = f"{names[0]} and {names[1]} share no {noun.plural}"
    else:
        listed = ", ".join(shared[:listed_items])
        more = len(shared) - listed_items
        counted = noun.singular if len(shared) == ONE_ITEM else noun.plural
        detail = (
            f"{names[0]} and {names[1]} share {len(shared)} {counted}: {listed}"
            + (f" and {more} more" if more > 0 else "")
        )
    return Factor(code=code, value=value, evidence=evidence, detail=detail)


def scalar_factor(code: str, value: float, *, detail: str, evidence: float = ONE) -> Factor:
    return Factor(code=code, value=max(ZERO, min(ONE, value)), evidence=evidence,
                  detail=detail)


def strength(factors: dict[str, Factor], weights: dict[str, float]) -> float:
    """The weighted sum the rubric describes."""
    return max(
        ZERO,
        min(ONE, sum(weights.get(code, ZERO) * factor.value
                     for code, factor in factors.items())),
    )


def confidence(factors: dict[str, Factor], weights: dict[str, float]) -> float:
    """How much of the weighted signal actually had evidence behind it.

    A weight whose factor had nothing to compare contributes nothing to
    confidence, so an edge assembled from one usable signal out of five is
    reported as the weak claim it is rather than as a fact.
    """
    total = sum(weights.values())
    if not total:
        return ZERO
    supported = sum(
        weights.get(code, ZERO) * factor.evidence for code, factor in factors.items()
    )
    return max(ZERO, min(ONE, supported / total))


def dominant(factors: dict[str, Factor], weights: dict[str, float]) -> Factor:
    """The signal that contributed most. It is what the rationale is written from."""
    return max(
        factors.values(),
        key=lambda factor: weights.get(factor.code, ZERO) * factor.value,
    )
