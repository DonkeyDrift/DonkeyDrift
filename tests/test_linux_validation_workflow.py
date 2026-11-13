from pathlib import Path

import yaml


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "linux-validation.yml"
)


def test_self_hosted_workflow_only_runs_for_trusted_push_or_dispatch():
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = data.get("on", data.get(True))
    job = data["jobs"]["linux-validation"]

    assert set(triggers) == {"push", "workflow_dispatch"}
    assert "pull_request" not in triggers
    assert job["steps"][0]["with"]["ref"] == "${{ github.sha }}"
    assert job["steps"][0]["with"]["persist-credentials"] is False
