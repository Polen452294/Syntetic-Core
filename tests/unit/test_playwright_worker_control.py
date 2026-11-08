import pytest

from syntetic_core._engine.browser import playwright_worker_control as guard


def original_source():
    return "\n".join(
        [
            f'this._client.send("Target.setAutoAttach", {guard.PARAMS})',
            f'session2.send("Target.setAutoAttach", {guard.PARAMS})',
            f'session2.send("Target.setAutoAttach", {guard.PARAMS})',
        ]
    )


def test_driver_patch_scopes_worker_ownership_and_is_idempotent():
    source = guard.patched_source(original_source())
    assert source.count("syntheticWorkerAttach(") == 4  # Three calls and the helper.
    assert guard.OWNER_FLAG in source
    assert "return params;" in source
    assert guard.patched_source(source) == source


def test_unknown_driver_layout_is_rejected_without_writing(tmp_path, monkeypatch):
    path = tmp_path / "driver.js"
    path.write_text("unknown driver layout", encoding="utf-8")
    monkeypatch.setattr(guard, "version", lambda _name: "1.62.0")
    monkeypatch.setattr(guard, "driver_path", lambda: path)
    with pytest.raises(RuntimeError, match="Unsupported Playwright driver layout"):
        guard.install()
    assert path.read_text(encoding="utf-8") == "unknown driver layout"


def test_unpinned_playwright_is_rejected(monkeypatch):
    monkeypatch.setattr(guard, "version", lambda _name: "1.63.0")
    with pytest.raises(RuntimeError, match="pinned Playwright"):
        guard.install()
