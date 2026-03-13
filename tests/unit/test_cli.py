from __future__ import annotations

import io
import logging
from pathlib import Path

from typer.testing import CliRunner

from remora.__main__ import _configure_logging, app


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
    log_path = tmp_path / ".remora" / "remora.log"
    assert log_path.exists()
    assert "Initializing runtime services" in log_path.read_text(encoding="utf-8")


def test_configure_logging_keeps_existing_root_handlers() -> None:
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    marker = logging.StreamHandler(io.StringIO())
    root_logger.addHandler(marker)

    try:
        _configure_logging("INFO")
        assert marker in root_logger.handlers
        assert root_logger.level == logging.INFO
    finally:
        root_logger.setLevel(original_level)
        for handler in list(root_logger.handlers):
            if handler not in original_handlers:
                root_logger.removeHandler(handler)
                handler.close()
