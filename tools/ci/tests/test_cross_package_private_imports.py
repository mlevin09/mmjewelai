"""Repository policy: no package imports another package's underscore names.

A name starting with ``_`` is an internal detail of its own package and may change without
notice. Code that needs it from another package must use a public name exported as part of
that package's contract. This static check covers module-level and function-local imports in
every ``src`` tree; tests may still exercise their own package's internals.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOTS = sorted(
    path.parent
    for pattern in ("packages/*/src/*", "workers/*/src/*", "apps/*/src/*")
    for path in ROOT.glob(pattern + "/__init__.py")
)
PACKAGES = {source.name: source for source in SOURCE_ROOTS}


def _private_cross_package_imports(source):
    own = source.name
    found = []
    for path in sorted(source.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
                continue
            provider = node.module.split(".")[0]
            if provider == own or provider not in PACKAGES:
                continue
            for alias in node.names:
                if alias.name.startswith("_") and not alias.name.startswith("__"):
                    relative = path.relative_to(ROOT).as_posix()
                    found.append(f"{relative}:{node.lineno} {node.module}.{alias.name}")
    return found


def test_inventory_covers_the_repository_packages():
    # Guards the guard: an empty glob would make the policy check pass vacuously.
    assert {"jewelai_api", "jewelai_parser", "jewelai_domain", "jewelai_prompts"} <= set(PACKAGES)


def test_no_package_imports_another_packages_private_names():
    violations = [
        item for source in SOURCE_ROOTS for item in _private_cross_package_imports(source)
    ]
    assert violations == [], "\n".join(violations)


def test_the_check_detects_a_violation(tmp_path):
    consumer = tmp_path / "jewelai_api"
    consumer.mkdir()
    (consumer / "module.py").write_text(
        "def f():\n    from jewelai_parser.full_message import _hidden\n", encoding="utf-8"
    )
    original_root = globals()["ROOT"]
    globals()["ROOT"] = tmp_path
    try:
        assert _private_cross_package_imports(consumer) == [
            "jewelai_api/module.py:2 jewelai_parser.full_message._hidden"
        ]
    finally:
        globals()["ROOT"] = original_root
