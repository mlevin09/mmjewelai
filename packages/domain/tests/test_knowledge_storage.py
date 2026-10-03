import json

import pytest
from test_knowledge_library import bundle

from jewelai_domain.knowledge_storage import (
    KnowledgeArtifactStorageError,
    KnowledgeArtifactStore,
)


def test_publish_round_trip_is_durable_and_idempotent(tmp_path):
    store = KnowledgeArtifactStore(tmp_path)
    first = store.publish(bundle())
    second = store.publish(bundle())

    assert first == second
    assert first.package_id == "jewelai.test.solitaire"
    assert first.artifact_version == "0.3.0"
    assert len(first.source_sha256) == 64
    assert len(first.runtime_sha256) == 64
    assert len(first.manifest_sha256) == 64

    release = tmp_path / "jewelai.test.solitaire" / "0.3.0"
    assert sorted(path.name for path in release.iterdir()) == [
        "checksums.json",
        "manifest.json",
        "runtime.json",
        "source.json",
    ]
    assert store.load(first.package_id, first.artifact_version) == first


def test_publish_rejects_same_identity_with_different_content(tmp_path):
    store = KnowledgeArtifactStore(tmp_path)
    store.publish(bundle())
    changed = bundle()
    changed["claims"][0]["statement"] = "Changed reviewed claim."

    with pytest.raises(KnowledgeArtifactStorageError, match="different content"):
        store.publish(changed)


def test_load_fails_closed_after_tampering(tmp_path):
    store = KnowledgeArtifactStore(tmp_path)
    stored = store.publish(bundle())
    source_path = tmp_path / stored.package_id / stored.artifact_version / "source.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["claims"][0]["statement"] = "Tampered"
    source_path.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(KnowledgeArtifactStorageError, match="checksum mismatch"):
        store.load(stored.package_id, stored.artifact_version)


@pytest.mark.parametrize(
    "package_id,version",
    [
        ("../escape", "1.0.0"),
        ("safe.package", "../1.0.0"),
        ("safe.package", ".."),
        ("safe.package", "."),
        ("safe.package", "1.0"),
        ("safe package", "1.0.0"),
        ("safe/package", "1.0.0"),
    ],
)
def test_storage_rejects_unsafe_paths(tmp_path, package_id, version):
    store = KnowledgeArtifactStore(tmp_path)
    with pytest.raises(KnowledgeArtifactStorageError, match="unsafe"):
        store.load(package_id, version)
