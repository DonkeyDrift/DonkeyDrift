from pathlib import Path

import yaml


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "linux-validation.yml"
)


def _load_workflow():
    text = WORKFLOW.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    triggers = data.get("on", data.get(True))
    return text, data, triggers


def test_workflow_runs_on_github_hosted_runner_without_self_hosted():
    text, data, _ = _load_workflow()
    job = data["jobs"]["linux-validation"]

    assert job["runs-on"] == "ubuntu-latest"
    assert "self-hosted" not in text


def test_workflow_triggers_on_pull_request_and_manual_dispatch_only():
    _, _, triggers = _load_workflow()

    assert set(triggers) == {"pull_request", "workflow_dispatch"}
    assert "push" not in triggers
    assert "pull_request_target" not in triggers


def test_checkout_pins_exact_pr_head_sha_without_persisted_credentials():
    _, data, _ = _load_workflow()
    checkout = data["jobs"]["linux-validation"]["steps"][0]

    assert checkout["with"]["ref"] == (
        "${{ github.event.pull_request.head.sha || github.sha }}"
    )
    assert checkout["with"]["persist-credentials"] is False


def test_patch_step_applies_gym_resilience_patch_to_installed_package():
    _, data, _ = _load_workflow()
    steps = data["jobs"]["linux-validation"]["steps"]

    patch_steps = [
        step for step in steps if "patch -p1" in str(step.get("run", ""))
    ]

    assert len(patch_steps) == 1
    run = patch_steps[0]["run"]
    assert "scripts/patches/gym-donkeycar-linux-resilience.patch" in run
    assert "gym_donkeycar" in run


def test_workflow_installs_full_pc_dependencies_for_root_collection():
    _, data, _ = _load_workflow()
    install_steps = [
        step for step in data["jobs"]["linux-validation"]["steps"]
        if step.get("name") == "Install dependencies"
    ]

    assert len(install_steps) == 1
    assert '".[pc,dev]"' in install_steps[0]["run"]
    assert "opencv-python-headless" in install_steps[0]["run"]
