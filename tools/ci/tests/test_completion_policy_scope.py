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
