"""Manifest validation with precise error messages and line numbers (M1.2).

Two layers:

1. **Schema.** Each manifest kind has a JSON Schema in ``manifests/schemas/``.
   A ``jsonschema`` error carries a JSON pointer, which the positional loader
   turns into a file, line and column plus the offending source line.
2. **Cross-manifest.** Rules a single-document schema cannot express: exactly one
   authoritative definition per KPI name (I1), coverage citing a KPI and a
   product that exist (I4), an agent reading only columns its products declare,
   demo exchanges numbered contiguously from 1, and golden answers that exist.

The validator never guesses. An unresolvable reference is an error, not a
warning, because rule 7 is to fail closed.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts._paths import MANIFESTS, REPO_ROOT
from scripts.manifests.loader import LoadedManifest, LoadError, load_manifest

SCHEMA_DIR = MANIFESTS / "schemas"

KIND_SCHEMA = {
    "DataProduct": "data_product.schema.json",
    "Agent": "agent.schema.json",
    "Kpi": "kpi.schema.json",
    "Taxonomy": "taxonomy.schema.json",
    "LearningPath": "learning_path.schema.json",
}


@dataclass(frozen=True)
class ValidationError:
    path: Path
    line: int
    column: int
    message: str
    source_line: str
    pointer: str

    def render(self) -> str:
        try:
            relative: Path | str = self.path.relative_to(REPO_ROOT)
        except ValueError:
            relative = self.path
        location = f"{relative}:{self.line}:{self.column}"
        pointer = self.pointer or "<document>"
        lines = [f"{location}: {self.message}", f"    at {pointer}"]
        if self.source_line.strip():
            lines.append(f"    | {self.source_line.rstrip()}")
        return "\n".join(lines)


def _registry() -> Registry:
    registry = Registry()
    for schema_path in sorted(SCHEMA_DIR.glob("*.json")):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        registry = registry.with_resource(
            schema["$id"],
            Resource.from_contents(schema, default_specification=DRAFT202012),
        )
    return registry


def _pointer(parts: list[Any]) -> str:
    tokens = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "".join(f"/{token}" for token in tokens)


def _error_from(manifest: LoadedManifest, pointer: str, message: str) -> ValidationError:
    position = manifest.position_of(pointer)
    line = position.line if position else 1
    column = position.column if position else 1
    return ValidationError(
        path=manifest.path,
        line=line,
        column=column,
        message=message,
        source_line=manifest.source_line(line),
        pointer=pointer,
    )


# jsonschema states what is wrong; a manifest author needs to be told what would
# be right. These keywords get the expected value spelled out in the message.
_EXPECTATION = {
    "minItems": "at least {value} item(s) are required",
    "maxItems": "at most {value} item(s) are allowed",
    "minLength": "at least {value} character(s) are required",
    "maxLength": "at most {value} character(s) are allowed",
    "minimum": "the value must be >= {value}",
    "maximum": "the value must be <= {value}",
    "minProperties": "at least {value} key(s) are required",
    "pattern": "the value must match {value}",
    "const": "the value must be {value}",
    "required": "these keys are required: {value}",
}


def _explain(error: Any) -> str:
    """Add the expected value to the message so the fix is stated, not implied."""
    template = _EXPECTATION.get(error.validator)
    if template is None:
        return str(error.message)
    value = error.validator_value
    if error.validator == "required":
        value = ", ".join(sorted(value))
    return f"{error.message} — {template.format(value=value)}"


def validate_document(manifest: LoadedManifest, registry: Registry) -> list[ValidationError]:
    data = manifest.data
    if not isinstance(data, dict):
        return [_error_from(manifest, "", "manifest must be a mapping at the top level")]

    kind = data.get("kind")
    if kind is None:
        return [
            _error_from(
                manifest,
                "",
                "missing 'kind'; expected one of " + ", ".join(sorted(KIND_SCHEMA)),
            )
        ]
    if kind == "Rubric" or (kind is None and "rubric" in data):
        schema_name = "rubric.schema.json"
    elif kind not in KIND_SCHEMA:
        return [
            _error_from(
                manifest,
                "/kind",
                f"unknown kind {kind!r}; expected one of " + ", ".join(sorted(KIND_SCHEMA)),
            )
        ]
    else:
        schema_name = KIND_SCHEMA[kind]

    schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, registry=registry)

    errors: list[ValidationError] = []
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        pointer = _pointer(list(error.absolute_path))
        errors.append(_error_from(manifest, pointer, _explain(error)))
    return errors


def validate_against(
    manifest: LoadedManifest, registry: Registry, schema_name: str
) -> list[ValidationError]:
    """Validate a manifest that names its own kind by a top-level key.

    Rubrics and policies are configuration rather than assets, so they carry
    ``rubric:`` or ``policy:`` at the top level instead of ``kind:``. The schema
    is chosen by the directory they live in.
    """
    schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, registry=registry)
    errors: list[ValidationError] = []
    for error in sorted(validator.iter_errors(manifest.data), key=lambda e: list(e.absolute_path)):
        errors.append(_error_from(manifest, _pointer(list(error.absolute_path)), _explain(error)))
    return errors


def validate_rubric(manifest: LoadedManifest, registry: Registry) -> list[ValidationError]:
    return validate_against(manifest, registry, "rubric.schema.json")


def validate_policy(manifest: LoadedManifest, registry: Registry) -> list[ValidationError]:
    return validate_against(manifest, registry, "policy.schema.json")


def _load_all(directory: Path) -> tuple[list[LoadedManifest], list[ValidationError]]:
    loaded: list[LoadedManifest] = []
    errors: list[ValidationError] = []
    if not directory.exists():
        return loaded, errors
    for path in sorted(directory.glob("*.yaml")):
        try:
            loaded.append(load_manifest(path))
        except LoadError as error:
            line = error.position.line if error.position else 1
            column = error.position.column if error.position else 1
            errors.append(
                ValidationError(
                    path=path,
                    line=line,
                    column=column,
                    message=f"YAML is not well formed: {error}",
                    source_line="",
                    pointer="",
                )
            )
    return loaded, errors


def cross_validate(
    products: list[LoadedManifest],
    agents: list[LoadedManifest],
    kpis: list[LoadedManifest],
    taxonomies: list[LoadedManifest] | None = None,
) -> list[ValidationError]:
    errors: list[ValidationError] = []

    kpi_ids = {m.data["metadata"]["id"]: m for m in kpis if isinstance(m.data, dict)}
    product_ids = {m.data["metadata"]["id"]: m for m in products if isinstance(m.data, dict)}

    # I1: exactly one authoritative definition per KPI name. Two files with the
    # same kpi_name fail generation with a side-by-side diff of the two.
    by_name: dict[str, list[LoadedManifest]] = defaultdict(list)
    for manifest in kpis:
        metadata = manifest.data.get("metadata", {})
        if metadata.get("status") in {"draft", "certified"}:
            by_name[str(metadata.get("name", "")).strip().lower()].append(manifest)
    for name, duplicates in sorted(by_name.items()):
        if len(duplicates) < 2:
            continue
        first, *rest = duplicates
        for other in rest:
            errors.append(
                _error_from(
                    other,
                    "/metadata/name",
                    "I1 violated: a second active definition for KPI name "
                    f"{name!r}\n{_side_by_side(first, other)}",
                )
            )

    # Every upstream source a product names must be in the source_system
    # taxonomy. The mesh draws its source-overlap edges from these codes and the
    # catalogue renders their labels, so a code that is in no vocabulary is an
    # edge between two products that nothing can name.
    source_codes = {
        entry["code"]
        for manifest in (taxonomies or [])
        if manifest.data.get("taxonomy") == "source_system"
        for entry in manifest.data.get("entries", [])
    }
    if source_codes:
        for manifest in products:
            for index, code in enumerate(manifest.data.get("spec", {}).get(
                "upstream_sources", []
            )):
                if code not in source_codes:
                    errors.append(
                        _error_from(
                            manifest,
                            f"/spec/upstream_sources/{index}",
                            f"upstream source {code!r} is not in the source_system taxonomy",
                        )
                    )

    for manifest in products:
        spec = manifest.data.get("spec", {})
        for index, kpi_id in enumerate(spec.get("certified_kpis", [])):
            if kpi_id not in kpi_ids:
                errors.append(
                    _error_from(
                        manifest,
                        f"/spec/certified_kpis/{index}",
                        f"certified KPI {kpi_id!r} has no manifest in manifests/kpis/",
                    )
                )
        declared = {column["name"] for column in spec.get("columns", [])}
        for index, rule in enumerate(spec.get("quality_rules", [])):
            targets = [rule["column"]] if "column" in rule else rule.get("columns", [])
            for target in targets:
                if target not in declared:
                    errors.append(
                        _error_from(
                            manifest,
                            f"/spec/quality_rules/{index}",
                            f"quality rule targets column {target!r} which the product "
                            "does not declare",
                        )
                    )
        dimensions = {rule["dimension"] for rule in spec.get("quality_rules", [])}
        for mandatory in ("completeness", "freshness", "validity"):
            if mandatory not in dimensions:
                errors.append(
                    _error_from(
                        manifest,
                        "/spec/quality_rules",
                        f"a {mandatory} rule is mandatory for every product",
                    )
                )

    # A KPI's expression must resolve against the columns of its source product.
    # A definition that references a column nobody publishes cannot be computed,
    # and finding that out at query time is finding it out too late.
    product_columns = {
        manifest.data["metadata"]["id"]: {
            column["name"] for column in manifest.data["spec"]["columns"]
        }
        for manifest in products
    }
    for manifest in kpis:
        spec = manifest.data.get("spec", {})
        source = spec.get("source_of_record")
        if source is None or source not in product_columns:
            continue
        for field in ("expression", "numerator_expr", "denominator_expr"):
            body = spec.get(field)
            if not body:
                continue
            unknown = sorted(
                identifier
                for identifier in _identifiers(body)
                if identifier not in product_columns[source]
            )
            if unknown:
                errors.append(
                    _error_from(
                        manifest,
                        f"/spec/{field}",
                        f"references {', '.join(unknown)}, which {source} does not publish",
                    )
                )

    for manifest in agents:
        spec = manifest.data.get("spec", {})
        bound_columns: dict[str, set[str]] = {}
        for index, binding in enumerate(spec.get("data_products", [])):
            product_id = binding["product_id"]
            bound_columns[product_id] = set(binding["columns"])
            product = product_ids.get(product_id)
            if product is None:
                errors.append(
                    _error_from(
                        manifest,
                        f"/spec/data_products/{index}/product_id",
                        f"agent binds product {product_id!r} which has no manifest",
                    )
                )
                continue
            declared = {c["name"] for c in product.data["spec"]["columns"]}
            unknown = sorted(set(binding["columns"]) - declared)
            if unknown:
                errors.append(
                    _error_from(
                        manifest,
                        f"/spec/data_products/{index}/columns",
                        f"columns not declared by {product_id}: {', '.join(unknown)}",
                    )
                )

        for index, coverage in enumerate(spec.get("kpi_coverage", [])):
            if coverage["kpi_id"] not in kpi_ids:
                errors.append(
                    _error_from(
                        manifest,
                        f"/spec/kpi_coverage/{index}/kpi_id",
                        f"I4 violated: coverage cites KPI {coverage['kpi_id']!r} "
                        "which has no manifest",
                    )
                )
            source = coverage["source_product"]
            if source not in bound_columns:
                errors.append(
                    _error_from(
                        manifest,
                        f"/spec/kpi_coverage/{index}/source_product",
                        f"coverage sources from {source!r} but the agent does not bind it",
                    )
                )
                continue
            unbound = sorted(set(coverage["columns_used"]) - bound_columns[source])
            if unbound:
                errors.append(
                    _error_from(
                        manifest,
                        f"/spec/kpi_coverage/{index}/columns_used",
                        "coverage reads columns outside the agent's binding on "
                        f"{source}: {', '.join(unbound)}",
                    )
                )

        exchanges = spec.get("demo_exchanges", [])
        ordinals = [exchange["ordinal"] for exchange in exchanges]
        if ordinals != list(range(1, len(ordinals) + 1)):
            errors.append(
                _error_from(
                    manifest,
                    "/spec/demo_exchanges",
                    f"demo exchange ordinals must run 1..{len(ordinals)} in order, got {ordinals}",
                )
            )
        for index, exchange in enumerate(exchanges):
            if exchange["kpi_class"] not in kpi_ids:
                errors.append(
                    _error_from(
                        manifest,
                        f"/spec/demo_exchanges/{index}/kpi_class",
                        f"demo exchange cites KPI {exchange['kpi_class']!r} which has no manifest",
                    )
                )
            golden = REPO_ROOT / exchange["golden_answer_ref"]
            if not golden.exists():
                errors.append(
                    _error_from(
                        manifest,
                        f"/spec/demo_exchanges/{index}/golden_answer_ref",
                        f"golden answer {exchange['golden_answer_ref']} does not exist",
                    )
                )
            for cited in exchange["expected_shape"]["must_cite"]:
                if cited.startswith("DP-") and cited not in product_ids:
                    errors.append(
                        _error_from(
                            manifest,
                            f"/spec/demo_exchanges/{index}/expected_shape/must_cite",
                            f"must_cite names product {cited!r} which has no manifest",
                        )
                    )
                if cited.startswith("KPI-") and cited not in kpi_ids:
                    errors.append(
                        _error_from(
                            manifest,
                            f"/spec/demo_exchanges/{index}/expected_shape/must_cite",
                            f"must_cite names KPI {cited!r} which has no manifest",
                        )
                    )

    return errors


# SQL keywords, functions and literals that appear in a KPI expression and are
# not column references.
SQL_VOCABULARY = frozenset(
    """
    select from where filter and or not null is in as by group order over partition within
    count sum avg min max distinct case when then else end coalesce nullif cast interval
    date timestamp true false percentile_cont percentile_disc ntile row_number rank dense_rank
    abs round floor ceil greatest least extract epoch desc asc
    """.split()
)

_IDENTIFIER = re.compile(r"\b[a-z_][a-z0-9_]*\b")


def _identifiers(expression: str) -> set[str]:
    """Column-like identifiers in a SQL expression, excluding SQL vocabulary."""
    without_strings = re.sub(r"'[^']*'", " ", expression.lower())
    return {
        token
        for token in _IDENTIFIER.findall(without_strings)
        if token not in SQL_VOCABULARY
    }


def _side_by_side(first: LoadedManifest, second: LoadedManifest) -> str:
    """Render the two conflicting definitions next to each other (M1 acceptance)."""

    def summarise(manifest: LoadedManifest) -> list[str]:
        metadata = manifest.data.get("metadata", {})
        spec = manifest.data.get("spec", {})
        return [
            f"id:         {metadata.get('id')}",
            f"status:     {metadata.get('status')}",
            f"steward:    {metadata.get('steward')}",
            f"definition: {str(spec.get('business_definition', ''))[:60]}",
            f"expression: {spec.get('expression') or spec.get('numerator_expr')}",
        ]

    left_title = str(first.path.name)
    right_title = str(second.path.name)
    left = summarise(first)
    right = summarise(second)
    width = max([len(left_title), *(len(line) for line in left)]) + 2

    rendered = [f"    {left_title.ljust(width)}| {right_title}"]
    rendered.append(f"    {'-' * width}+{'-' * (len(right_title) + 1)}")
    for left_line, right_line in zip(left, right, strict=True):
        rendered.append(f"    {left_line.ljust(width)}| {right_line}")
    return "\n".join(rendered)


def validate_all(root: Path | None = None) -> list[ValidationError]:
    """Validate every manifest under ``root`` (defaults to ``manifests/``)."""
    manifests_root = root or MANIFESTS
    registry = _registry()
    errors: list[ValidationError] = []

    products, load_errors = _load_all(manifests_root / "products")
    errors.extend(load_errors)
    agents, load_errors = _load_all(manifests_root / "agents")
    errors.extend(load_errors)
    kpis, load_errors = _load_all(manifests_root / "kpis")
    errors.extend(load_errors)
    taxonomies, load_errors = _load_all(manifests_root / "taxonomies")
    errors.extend(load_errors)
    rubrics, load_errors = _load_all(manifests_root / "rubrics")
    errors.extend(load_errors)
    policies, load_errors = _load_all(manifests_root / "policies")
    errors.extend(load_errors)

    academy, load_errors = _load_all(manifests_root / "academy")
    errors.extend(load_errors)

    for manifest in [*products, *agents, *kpis, *taxonomies, *academy]:
        errors.extend(validate_document(manifest, registry))
    for manifest in rubrics:
        errors.extend(validate_rubric(manifest, registry))
    for manifest in policies:
        errors.extend(validate_policy(manifest, registry))

    # Cross-manifest rules only make sense once every document parses.
    if not errors:
        errors.extend(cross_validate(products, agents, kpis, taxonomies))

    return errors


def main() -> int:
    errors = validate_all()
    if not errors:
        print("manifests: valid")
        return 0
    print(f"manifests: {len(errors)} error(s)\n")
    for error in errors:
        print(error.render())
        print()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
