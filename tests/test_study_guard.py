"""``study test`` runs the pre-registered test period once (M1).

The guard refuses a second run when the test-period result already exists (the results
file or a recorded ``runs/study-test-*.json``) unless the override flag is given. Every
study step is replaced by a stub: no real data is read and nothing is computed.
"""

from __future__ import annotations

import pytest

from bist_harness.backtest import study

OVERRIDE = "--i-know-this-reruns-the-test-period"


@pytest.fixture
def stubbed(monkeypatch):
    ran: list[str] = []

    def step(name, value):
        def run(*args, **kwargs):
            ran.append(name)
            return value

        return run

    monkeypatch.setattr(study, "backtests", step("backtests", {}))
    monkeypatch.setattr(study, "reactions", step("reactions", {"summary": {}}))
    monkeypatch.setattr(study, "scenario_1", step("scenario_1", {}))
    monkeypatch.setattr(study, "scenario_2", step("scenario_2", {}))
    monkeypatch.setattr(study, "scenario_3", step("scenario_3", {}))
    return ran


def run(tmp_path, *args):
    return study.main(
        ["test", *args], results_file=tmp_path / "test-period.md", runs_dir=tmp_path / "runs"
    )


def test_a_recorded_results_file_stops_a_second_test_run(tmp_path, stubbed, capsys):
    (tmp_path / "test-period.md").write_text("# results\n", encoding="utf-8")
    assert run(tmp_path) != 0
    assert stubbed == []
    out = capsys.readouterr().out
    assert "already" in out and OVERRIDE in out
    assert not (tmp_path / "runs").exists()


def test_a_recorded_run_file_stops_a_second_test_run(tmp_path, stubbed):
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "study-test-20261117-120000.json").write_text("{}", encoding="utf-8")
    assert run(tmp_path) != 0
    assert stubbed == []


def test_the_first_test_run_and_an_explicit_override_run(tmp_path, stubbed):
    assert run(tmp_path) == 0  # nothing recorded yet
    assert len(list((tmp_path / "runs").glob("study-test-*.json"))) == 1
    stubbed.clear()
    assert run(tmp_path, OVERRIDE) == 0
    assert "backtests" in stubbed


def test_the_discovery_period_is_not_guarded(tmp_path, stubbed):
    (tmp_path / "test-period.md").write_text("# results\n", encoding="utf-8")
    assert (
        study.main(
            ["discovery"], results_file=tmp_path / "test-period.md", runs_dir=tmp_path / "runs"
        )
        == 0
    )


def test_the_override_flag_says_it_breaks_the_pre_registration(capsys):
    assert study.main([]) == 2
    out = capsys.readouterr().out
    assert OVERRIDE in out and "pre-registration" in out
