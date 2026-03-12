from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from remora.__main__ import app


def test_cli_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Remora" in result.stdout
    assert "start" in result.stdout


def test_cli_start_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["start", "--help"])
    assert result.exit_code == 0
    assert "--project-root" in result.stdout
    assert "--no-web" in result.stdout


def test_cli_start_smoke(tmp_path: Path) -> None:
    runner = CliRunner()
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("def a():\n    return 1\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "start",
            "--project-root",
            str(tmp_path),
            "--no-web",
            "--run-seconds",
            "0.1",
        ],
    )

    assert result.exit_code == 0
    assert (tmp_path / ".remora" / "remora.db").exists()
