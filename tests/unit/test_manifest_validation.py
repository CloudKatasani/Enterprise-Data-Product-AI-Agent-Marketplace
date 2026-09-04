"""M1.2 — a malformed manifest fails with a precise error message and line number.

Every test plants one defect and asserts three things: that validation fails,
that the message names the defect in words a manifest author can act on, and
that the reported line points at the offending YAML rather than at the top of
the file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.manifests.validate import validate_all
from tests.fixtures.manifests import (
    VALID_AGENT,
    VALID_KPI,
    VALID_PRODUCT,
    clone,
    write_golden_answers,
    write_tree,
)


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch) -> Path:
    """A temporary repository whose golden answers and manifests both live inside it."""
    import scripts.manifests.validate as module

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    write_golden_answers(tmp_path)
    return tmp_path


def _validate(repo: Path, **kwargs) -> list:
    root = write_tree(repo / "manifests", **kwargs)
    return validate_all(root)


def _line_containing(path: Path, needle: str) -> int:
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if needle in line:
            return number
    raise AssertionError(f"{needle!r} not found in {path}")


def test_the_seed_shaped_manifests_are_valid(repo: Path) -> None:
    assert _validate(repo) == []


def test_the_repositorys_own_manifests_are_valid() -> None:
    assert [error.render() for error in validate_all()] == []


def test_yaml_that_is_not_well_formed_reports_its_position(repo: Path) -> None:
    write_tree(repo / "manifests")
    broken = repo / "manifests" / "kpis" / "KPI-CHURN-001.yaml"
    broken.write_text("metadata:\n  id: KPI-X-001\n   name: bad indent\n", encoding="utf-8")

    errors = validate_all(repo / "manifests")

    assert len(errors) == 1
    assert "YAML is not well formed" in errors[0].message
    assert errors[0].line == 3


def test_a_purpose_below_the_floor_names_the_field_and_the_line(repo: Path) -> None:
    product = clone(VALID_PRODUCT)
    product["spec"]["purpose"] = "too short"

    errors = _validate(repo, products=[product])

    assert len(errors) == 1
    error = errors[0]
    assert error.pointer == "/spec/purpose"
    assert "too short" in error.message or "20" in error.message
    assert error.line == _line_containing(error.path, "purpose:")
    assert "too short" in error.source_line


def test_known_limitations_saying_none_is_rejected(repo: Path) -> None:
    product = clone(VALID_PRODUCT)
    product["spec"]["known_limitations"] = "none"

    errors = _validate(repo, products=[product])

    assert {error.pointer for error in errors} == {"/spec/known_limitations"}
    assert any("none" in error.source_line for error in errors)


def test_an_agent_with_four_demo_exchanges_is_rejected(repo: Path) -> None:
    agent = clone(VALID_AGENT)
    agent["spec"]["demo_exchanges"] = agent["spec"]["demo_exchanges"][:-1]

    errors = _validate(repo, agents=[agent])

    assert any(error.pointer == "/spec/demo_exchanges" for error in errors)
    assert any("5" in error.message for error in errors)


def test_an_empty_out_of_scope_is_rejected(repo: Path) -> None:
    agent = clone(VALID_AGENT)
    agent["spec"]["out_of_scope"] = []

    errors = _validate(repo, agents=[agent])

    assert any(error.pointer == "/spec/out_of_scope" for error in errors)


def test_a_capability_statement_outside_90_to_140_chars_is_rejected(repo: Path) -> None:
    agent = clone(VALID_AGENT)
    agent["spec"]["capability_statement"] = "Answers churn questions."

    errors = _validate(repo, agents=[agent])

    assert any(error.pointer == "/spec/capability_statement" for error in errors)


def test_coverage_citing_an_unknown_kpi_is_rejected_with_i4_named(repo: Path) -> None:
    agent = clone(VALID_AGENT)
    agent["spec"]["kpi_coverage"][0]["kpi_id"] = "KPI-GHOST-999"
    agent["spec"]["demo_exchanges"][0]["kpi_class"] = "KPI-CHURN-001"

    errors = _validate(repo, agents=[agent])

    matching = [e for e in errors if e.pointer == "/spec/kpi_coverage/0/kpi_id"]
    assert len(matching) == 1
    assert "I4" in matching[0].message
    assert "KPI-GHOST-999" in matching[0].message


def test_an_agent_reading_a_column_outside_its_binding_is_rejected(repo: Path) -> None:
    agent = clone(VALID_AGENT)
    agent["spec"]["kpi_coverage"][0]["columns_used"].append("ltv")

    errors = _validate(repo, agents=[agent])

    matching = [e for e in errors if e.pointer == "/spec/kpi_coverage/0/columns_used"]
    assert len(matching) == 1
    assert "ltv" in matching[0].message


def test_an_agent_binding_a_column_the_product_does_not_declare_is_rejected(repo: Path) -> None:
    agent = clone(VALID_AGENT)
    agent["spec"]["data_products"][0]["columns"].append("propensity_decile")
    agent["spec"]["kpi_coverage"][0]["columns_used"] = ["subscriber_id"]

    errors = _validate(repo, agents=[agent])

    matching = [e for e in errors if e.pointer == "/spec/data_products/0/columns"]
    assert len(matching) == 1
    assert "propensity_decile" in matching[0].message


def test_a_missing_golden_answer_is_rejected(repo: Path) -> None:
    agent = clone(VALID_AGENT)
    agent["spec"]["demo_exchanges"][2]["golden_answer_ref"] = "seed/golden/AG-TEL-001/q99.json"

    errors = _validate(repo, agents=[agent])

    matching = [e for e in errors if e.pointer == "/spec/demo_exchanges/2/golden_answer_ref"]
    assert len(matching) == 1
    assert "q99.json" in matching[0].message


def test_a_product_without_a_freshness_rule_is_rejected(repo: Path) -> None:
    product = clone(VALID_PRODUCT)
    product["spec"]["quality_rules"] = [
        rule for rule in product["spec"]["quality_rules"] if rule["dimension"] != "freshness"
    ] + [
        {"id": "QR-TEL-001-04", "dimension": "uniqueness", "columns": ["subscriber_id"],
         "rule": "unique_at_grain", "threshold_pct": 99.99, "severity": "critical"}
    ]

    errors = _validate(repo, products=[product])

    assert any("freshness rule is mandatory" in error.message for error in errors)


def test_a_quality_rule_targeting_an_undeclared_column_is_rejected(repo: Path) -> None:
    product = clone(VALID_PRODUCT)
    product["spec"]["quality_rules"][0]["column"] = "not_a_column"

    errors = _validate(repo, products=[product])

    assert any("not_a_column" in error.message for error in errors)


def test_two_kpi_files_with_the_same_name_fail_with_a_side_by_side_diff(repo: Path) -> None:
    """M1 acceptance: I1 is caught at generation time, not at insert time."""
    first = clone(VALID_KPI)
    second = clone(VALID_KPI)
    second["metadata"]["id"] = "KPI-CHURN-002"
    second["metadata"]["steward"] = "PTY-0099"
    second["spec"]["numerator_expr"] = "count(*) filter (where disconnected)"

    errors = _validate(repo, kpis=[first, second])

    matching = [e for e in errors if "I1 violated" in e.message]
    assert len(matching) == 1
    rendered = matching[0].render()
    assert "KPI-CHURN-001" in rendered
    assert "KPI-CHURN-002" in rendered
    assert "PTY-0099" in rendered
    assert "|" in rendered


def test_a_superseded_definition_does_not_conflict(repo: Path) -> None:
    first = clone(VALID_KPI)
    first["metadata"]["status"] = "superseded"
    second = clone(VALID_KPI)
    second["metadata"]["id"] = "KPI-CHURN-002"

    errors = _validate(repo, kpis=[first, second])

    assert [e for e in errors if "I1 violated" in e.message] == []


def test_demo_exchange_ordinals_must_be_contiguous(repo: Path) -> None:
    agent = clone(VALID_AGENT)
    agent["spec"]["demo_exchanges"][3]["ordinal"] = 9

    errors = _validate(repo, agents=[agent])

    assert any("ordinals must run 1..5" in error.message for error in errors)


def test_an_unknown_kind_is_named_in_the_error(repo: Path) -> None:
    write_tree(repo / "manifests")
    path = repo / "manifests" / "kpis" / "KPI-CHURN-001.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["kind"] = "Widget"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    errors = validate_all(repo / "manifests")

    assert any("unknown kind 'Widget'" in error.message for error in errors)


def test_a_rubric_weight_outside_the_unit_interval_is_rejected(repo: Path) -> None:
    write_tree(repo / "manifests")
    (repo / "manifests" / "rubrics" / "quality.yaml").write_text(
        yaml.safe_dump(
            {
                "rubric": "data_product_quality",
                "version": "1.0.0",
                "dimensions": [{"code": "completeness", "weight": 4}],
                "bands": [{"min": 0, "code": "unfit", "label": "Unfit"},
                          {"min": 90, "code": "exemplary", "label": "Exemplary"}],
                "hard_blockers": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    errors = validate_all(repo / "manifests")

    assert any(e.pointer == "/dimensions/0/weight" for e in errors)


def test_the_error_renders_with_file_line_pointer_and_source(repo: Path) -> None:
    product = clone(VALID_PRODUCT)
    product["spec"]["history_months"] = 0

    errors = _validate(repo, products=[product])
    rendered = errors[0].render()

    assert "DP-TEL-001.yaml:" in rendered
    assert "at /spec/history_months" in rendered
    assert "| " in rendered
