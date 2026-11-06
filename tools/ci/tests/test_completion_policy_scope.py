"""Complete completion-policy ownership without weakening shared Full qualification."""

from test_pr_selection import selected, targets


def test_completion_policy_requires_all_owning_scopes_and_shared_full_gate():
    resource = "data/completion/proposed-1.0.0.json"
    result = selected(
        resource,
        "apps/api/src/jewelai_api/app.py",
        "packages/persistence/src/jewelai_persistence/models.py",
    )
    scopes = {"packages/domain/tests", "packages/prompts/tests", "apps/api/tests/completion"}
    assert scopes <= targets(result)
    assert set(result["fixture_dependencies"][resource]["test_scopes"]) == scopes
    assert result["fixture_dependencies"][resource]["coverage"] == "complete_scope"
    assert result["blocked_reasons"] == []
    assert result["full_regression_required"]
    assert set(result["full_reasons"]) >= {
        "shared_api_dispatch",
        "shared_authority_schema_or_migration",
    }
    assert selected("data/unowned-new-policy.json")["blocked_reasons"] == ["unmapped_fixture_data"]


def test_preprod_activation_delegates_only_existing_infrastructure_check_paths():
    from pathlib import Path

    result = selected("infra/terraform/preprod/services.tf", "infra/terraform/preprod/README.md")
    assert not result["relevant"] and not result["suites"]
    assert result["blocked_reasons"] == []
    assert "Infrastructure" in result["delegated_check"]
    root = Path(__file__).resolve().parents[3]
    workflow = (root / ".github/workflows/infra.yml").read_text()
    assert "branches: [jewelai-v2]" in workflow and "- infra/**" in workflow
    assert "terraform -chdir=infra/terraform/preprod validate" in workflow
    assert "python infra/terraform/check_invariants.py" in workflow
    assert selected("infra/terraform/preprod/new-behavior.tf")["blocked_reasons"]


def test_preprod_activation_still_requires_complete_completion_coverage():
    result = selected(
        "infra/terraform/preprod/services.tf",
        "infra/terraform/preprod/README.md",
        "data/completion/preprod-no-defaults-1.0.0.json",
    )
    assert result["relevant"] and result["blocked_reasons"] == []
    assert {
        "packages/domain/tests",
        "packages/prompts/tests",
        "apps/api/tests/completion",
    } <= targets(result)
