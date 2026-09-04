"""Embeddings for the semantic half of hybrid search.

The marketplace does not ship a model. It ships an interface and one
implementation that needs nothing: a deterministic hashing embedder that
projects word and character n-grams into the vector space. It is semantic in the
weak sense — documents sharing vocabulary land near each other — and it is
reproducible, which matters more here than absolute quality: a search result
that changes because a hosted model was retrained is not a result anyone can
debug.

A deployment with a real embedding model implements :class:`Embedder` and
registers it at boot. Nothing above this module knows which one is in use.

Two kinds of number are kept apart. The **dimension** is a property of the
schema — it must equal the ``vector(n)`` column type — so it is generated from
the canonical model. The **feature weights and n-gram size** are tuning, so they
live in the ``semantic_search`` rubric and arrive through the constructor.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from services.common.rubrics import Rubric

RUBRIC_CODE = "semantic_search"

# The dimension is generated from the canonical model's vector(n) column type.
# It is read rather than imported so that adding generated/ to sys.path — and
# scattering bytecode through a directory that must stay byte-identical — is
# never necessary.
_MODEL_CONSTANTS = (
    Path(__file__).resolve().parents[2] / "generated" / "types" / "model_constants.py"
)
_DIMENSION_DECLARATION = re.compile(r"^EMBEDDING_DIMENSIONS\s*=\s*(\d+)\s*$", re.MULTILINE)


def _embedding_dimensions() -> int:
    match = _DIMENSION_DECLARATION.search(_MODEL_CONSTANTS.read_text(encoding="utf-8"))
    if match is None:
        raise RuntimeError(
            f"{_MODEL_CONSTANTS} declares no EMBEDDING_DIMENSIONS; run npm run gen"
        )
    return int(match.group(1))


DIMENSIONS = _embedding_dimensions()

_TOKEN = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    model_id: str

    def embed(self, text: str) -> list[float]: ...


class EmbedderNotConfigured(RuntimeError):
    """No embedder was registered. Fail closed rather than guess a configuration."""


@dataclass(frozen=True)
class HashingConfig:
    model_id: str
    word_unigram_weight: float
    word_bigram_weight: float
    char_ngram_weight: float
    char_ngram_size: int

    @classmethod
    def from_rubric(cls, rubric: Rubric) -> HashingConfig:
        return cls(
            model_id=rubric.text("embedder.model_id"),
            word_unigram_weight=float(rubric.number("embedder.word_unigram_weight")),
            word_bigram_weight=float(rubric.number("embedder.word_bigram_weight")),
            char_ngram_weight=float(rubric.number("embedder.char_ngram_weight")),
            char_ngram_size=int(rubric.number("embedder.char_ngram_size")),
        )


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class HashingEmbedder:
    """Deterministic, dependency-free, reproducible across processes and machines."""

    def __init__(self, config: HashingConfig) -> None:
        self._config = config
        self.model_id = config.model_id

    def _features(self, text: str) -> list[tuple[str, float]]:
        words = _tokens(text)
        config = self._config
        features: list[tuple[str, float]] = [
            (f"w:{word}", config.word_unigram_weight) for word in words
        ]
        features += [
            (f"b:{first}_{second}", config.word_bigram_weight)
            for first, second in zip(words, words[1:], strict=False)
        ]
        size = config.char_ngram_size
        for word in words:
            padded = f"^{word}$"
            for index in range(max(len(padded) - size + 1, 1)):
                features.append((f"c:{padded[index : index + size]}", config.char_ngram_weight))
        return features

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * DIMENSIONS
        for feature, weight in self._features(text):
            digest = hashlib.blake2b(feature.encode("utf-8")).digest()
            index = int.from_bytes(digest, "big") % DIMENSIONS
            # The low bit decides the sign, so unrelated features that collide
            # tend to cancel rather than reinforce.
            sign = -1.0 if digest[-1] & 1 else 1.0
            vector[index] += sign * weight

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


_ACTIVE: Embedder | None = None


def active_embedder() -> Embedder:
    if _ACTIVE is None:
        raise EmbedderNotConfigured(
            "no embedder is registered; call configure_from_rubric() at boot"
        )
    return _ACTIVE


def register_embedder(embedder: Embedder) -> None:
    """Install a deployment's own model. Called once at boot, never per request."""
    global _ACTIVE
    _ACTIVE = embedder


def configure_from_rubric(rubric: Rubric) -> Embedder:
    embedder = HashingEmbedder(HashingConfig.from_rubric(rubric))
    register_embedder(embedder)
    return embedder


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))
