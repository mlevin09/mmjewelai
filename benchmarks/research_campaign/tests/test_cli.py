import json
import sys

import pytest

from jewelai_research.cli import main


def test_cli_operator_init_and_closed_local_auth(campaign, tmp_path, monkeypatch, capsys):
    paths = campaign.inputs.paths
    common = [
        "jewelai-research",
        "init-synthetic",
        "--store",
        str(tmp_path / "cli-private"),
        "--corpus",
        str(paths[0]),
        "--manifest",
        str(paths[1]),
    ]
    monkeypatch.setattr(sys, "argv", common)
    main()
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["mode"] == "SYNTHETIC" and len(receipt["envelope_sha256"]) == 64
    common[1] = "serve"
    monkeypatch.delenv("JEWELAI_RESEARCH_LOCAL_TOKEN", raising=False)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "rejected" in capsys.readouterr().err


def test_cli_cannot_import_unapproved_activation(campaign, tmp_path, monkeypatch, capsys):
    file = tmp_path / "untrusted-envelope.json"
    e = campaign.envelope.copy()
    e["target"] = {"vm": "another"}
    file.write_text(json.dumps(e))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "jewelai-research",
            "activate",
            "--store",
            str(tmp_path / "other-private"),
            "--corpus",
            str(campaign.inputs.paths[0]),
            "--manifest",
            str(campaign.inputs.paths[1]),
            "--evaluator",
            str(campaign.inputs.paths[2]),
            "--envelope",
            str(file),
        ],
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "another" not in capsys.readouterr().err
