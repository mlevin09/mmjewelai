"""Static guard: the Prompt Enrichment runtime modules import in one direction only.

``prompt_enrichment_runtime_v2`` (F04 workflow) and the V1 service share their contracts
through ``prompt_enrichment_contracts``. V2 must never import the V1 service module, and
the V1 service must delegate to V2 through a module-level import rather than imports
hidden inside methods. A violation reintroduces the circular dependency.
"""

import ast
from pathlib import Path

import jewelai_api.prompt_enrichment_contracts as contracts
import jewelai_api.prompt_enrichment_runtime as runtime

PACKAGE = Path(runtime.__file__).parent
V1 = "prompt_enrichment_runtime"
V2 = "prompt_enrichment_runtime_v2"
CONTRACTS = "prompt_enrichment_contracts"


def _imports(module):
    """Return (module-level targets, function-local targets) of relative imports."""
    tree = ast.parse((PACKAGE / f"{module}.py").read_text())
    top_level = {id(node) for node in tree.body}
    module_level, local = set(), set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level != 1:
            continue
        targets = {node.module} if node.module else {alias.name for alias in node.names}
        (module_level if id(node) in top_level else local).update(targets)
    return module_level, local


def test_v2_and_contracts_never_import_the_v1_service():
    for module in (V2, CONTRACTS):
        module_level, local = _imports(module)
        assert V1 not in module_level | local, module


def test_contracts_import_neither_runtime_module():
    module_level, local = _imports(CONTRACTS)
    assert not ({V1, V2} & (module_level | local))


def test_v1_delegates_to_v2_through_a_module_level_import_only():
    module_level, local = _imports(V1)
    assert {V2, CONTRACTS} <= module_level
    assert V2 not in local


def test_v1_re_exports_the_same_contract_objects():
    for name in (
        "PromptEnrichmentRuntimeError",
        "PromptEnrichmentRuntimeErrorCode",
        "PromptEnrichmentWorkflowStatus",
        "PromptEnrichmentWorkflowStateV2",
        "InitialEnrichmentRequestV2",
        "PersistedClarificationAnswerRequestV2",
        "PersistedUserCorrectionRequestV2",
        "InitialEnrichmentRuntimeResultV2",
    ):
        assert getattr(runtime, name) is getattr(contracts, name), name
