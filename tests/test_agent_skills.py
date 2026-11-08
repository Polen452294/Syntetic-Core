import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_helper(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    module = load_helper(ROOT / "skills/syntetic-core/scripts/runtime.py")
    monkeypatch.setattr(module, "SKILL", tmp_path / "installed-skill")
    module.SKILL.mkdir()
    monkeypatch.delenv("SYNTETIC_CORE_HOME", raising=False)
    monkeypatch.setenv("SYNTETIC_CORE_SKILL_RUNTIME", str(tmp_path / "runtime-cache"))
    return module


def fake_project(runtime, path):
    path.mkdir()
    (path / "pyproject.toml").write_text('[project]\nname="syntetic-core"\n')
    python = runtime.interpreter(path / ".venv")
    python.parent.mkdir(parents=True)
    python.touch()
    return path


def test_explicit_runtime_rejects_invalid_home_instead_of_silent_fallback(runtime, monkeypatch):
    monkeypatch.setenv("SYNTETIC_CORE_HOME", str(runtime.SKILL / "missing"))
    with pytest.raises(ValueError, match="SYNTETIC_CORE_HOME"):
        runtime.locate()


def test_installed_pointer_resolves_checkout_with_spaces(runtime, tmp_path):
    project = fake_project(runtime, tmp_path / "Project with spaces")
    (runtime.SKILL / "runtime.json").write_text(json.dumps({"project_root": str(project)}))
    assert runtime.locate()["python"] == str(runtime.interpreter(project / ".venv").resolve())


def test_missing_checkout_falls_back_to_bootstrapped_runtime(runtime):
    (runtime.SKILL / "runtime.json").write_text(json.dumps({"project_root": "missing"}))
    directory = runtime.managed_home()
    runtime.interpreter(directory).parent.mkdir(parents=True)
    runtime.interpreter(directory).touch()
    (directory / ".syntetic-core-runtime.json").write_text(
        json.dumps({"package": "syntetic-core", "ready": True})
    )
    assert runtime.locate()["kind"] == "managed"


def test_incomplete_bootstrap_is_not_advertised_as_ready(runtime):
    directory = runtime.managed_home()
    runtime.interpreter(directory).parent.mkdir(parents=True)
    runtime.interpreter(directory).touch()
    (directory / ".syntetic-core-runtime.json").write_text(
        json.dumps({"package": "syntetic-core", "ready": False})
    )
    with pytest.raises(FileNotFoundError):
        runtime.locate()


@pytest.mark.parametrize(
    "command,tail",
    [("cli", ["--profiles", "C:/job with spaces", "doctor"]), ("python", ["-c", "print('ok')"])],
)
def test_launcher_preserves_arguments_and_does_not_use_shell(runtime, monkeypatch, command, tail):
    monkeypatch.setattr(runtime, "locate", lambda: {"python": "C:/runtime with spaces/python.exe"})
    run = Mock(return_value=Mock(returncode=7))
    monkeypatch.setattr(runtime.subprocess, "run", run)
    monkeypatch.setenv("PYTHONPATH", "unrelated-project")
    monkeypatch.setenv("PYTHONHOME", "unrelated-home")
    monkeypatch.setattr(sys, "argv", ["runtime.py", command, *tail])
    assert runtime.main() == 7
    assert run.call_args.args[0][0] == "C:/runtime with spaces/python.exe"
    assert run.call_args.args[0][-len(tail) :] == tail
    assert "PYTHONPATH" not in run.call_args.kwargs["env"]
    assert "PYTHONHOME" not in run.call_args.kwargs["env"]
    assert "shell" not in run.call_args.kwargs
    assert "cwd" not in run.call_args.kwargs


def test_setup_refuses_unmanaged_environment(runtime, tmp_path):
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    with pytest.raises(FileExistsError, match="unmanaged"):
        runtime.setup(unrelated)


@pytest.fixture
def installer(tmp_path):
    module = load_helper(ROOT / "tools/install_agent_skills.py")
    source = tmp_path / "skill-source"
    for relative in (
        "SKILL.md",
        "scripts/runtime.py",
        "assets/requirements.lock",
        "assets/syntetic_core-0.1.0-py3-none-any.whl",
    ):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test content")
    return module, source


def test_installer_is_repeatable_and_records_runtime_pointer(installer, tmp_path):
    module, source = installer
    target = tmp_path / "personal skills/syntetic-core"
    module.install_one(source, target, ROOT)
    first = (target / module.STAMP).read_bytes()
    module.install_one(source, target, ROOT)
    assert (target / module.STAMP).read_bytes() == first
    assert json.loads((target / "runtime.json").read_text())["project_root"] == str(ROOT)


def test_installer_preserves_locally_modified_skill(installer, tmp_path):
    module, source = installer
    target = tmp_path / "syntetic-core"
    module.install_one(source, target, ROOT)
    (target / "SKILL.md").write_text("local edits")
    with pytest.raises(ValueError, match="local changes"):
        module.install_one(source, target, ROOT)
    assert (target / "SKILL.md").read_text() == "local edits"


def test_installer_never_adopts_existing_unmanaged_skill(installer, tmp_path):
    module, source = installer
    target = tmp_path / "syntetic-core"
    target.mkdir()
    with pytest.raises(FileExistsError, match="not managed"):
        module.install_one(source, target, ROOT)
