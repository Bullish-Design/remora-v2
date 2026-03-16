"""Remora CLI entry point (Typer-based)."""

from __future__ import annotations

import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Annotated

import typer

from remora.code.discovery import CSTNode
from remora.code.discovery import discover as discover_nodes
from remora.code.paths import resolve_discovery_paths, resolve_query_paths
from remora.core.config import load_config
from remora.core.lifecycle import RemoraLifecycle
from remora.lsp import create_lsp_server_standalone

app = typer.Typer(
    name="remora",
    help="Remora - event-driven graph agent runner.",
    no_args_is_help=True,
    add_completion=False,
)


class _ContextFilter(logging.Filter):
    """Inject default structured context fields for non-actor log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "node_id"):
            record.node_id = "-"
        if not hasattr(record, "correlation_id"):
            record.correlation_id = "-"
        if not hasattr(record, "turn"):
            record.turn = "-"
        return True


PROJECT_ROOT_ARG = typer.Option(
    "--project-root",
    exists=True,
    file_okay=False,
    dir_okay=True,
)
CONFIG_ARG = typer.Option("--config")
PORT_ARG = typer.Option("--port", min=1, max=65535)
BIND_ARG = typer.Option(
    "--bind",
    help="Address to bind the web server to (use 0.0.0.0 for all interfaces).",
)
NO_WEB_ARG = typer.Option("--no-web")
RUN_SECONDS_ARG = typer.Option(
    "--run-seconds",
    help="Run for N seconds then shut down (useful for smoke tests).",
)
LOG_LEVEL_ARG = typer.Option(
    "--log-level",
    help="Python logging level (DEBUG, INFO, WARNING, ERROR).",
)
LOG_EVENTS_ARG = typer.Option(
    "--log-events/--no-log-events",
    help="Emit one runtime log line for each persisted event.",
)
LSP_ARG = typer.Option(
    "--lsp",
    help="Start the optional LSP server on stdin/stdout after runtime services are ready.",
)


@app.command("start")
def start_command(
    project_root: Annotated[Path, PROJECT_ROOT_ARG] = Path("."),
    config_path: Annotated[Path | None, CONFIG_ARG] = None,
    port: Annotated[int, PORT_ARG] = 8080,
    bind: Annotated[str, BIND_ARG] = "127.0.0.1",
    no_web: Annotated[bool, NO_WEB_ARG] = False,
    run_seconds: Annotated[float, RUN_SECONDS_ARG] = 0.0,
    log_level: Annotated[str, LOG_LEVEL_ARG] = "INFO",
    log_events: Annotated[bool, LOG_EVENTS_ARG] = False,
    lsp: Annotated[bool, LSP_ARG] = False,
) -> None:
    """Start Remora components and run until interrupted."""
    _configure_logging(log_level, lsp_mode=lsp)
    try:
        asyncio.run(
            _start(
                project_root=project_root,
                config_path=config_path,
                port=port,
                bind=bind,
                no_web=no_web,
                run_seconds=run_seconds,
                log_events=log_events,
                lsp=lsp,
            )
        )
    except KeyboardInterrupt:
        pass


@app.command("discover")
def discover_command(
    project_root: Annotated[Path, PROJECT_ROOT_ARG] = Path("."),
    config_path: Annotated[Path | None, CONFIG_ARG] = None,
) -> None:
    """Run discovery and print a node summary."""
    nodes = asyncio.run(_discover(project_root=project_root, config_path=config_path))
    typer.echo(f"Discovered {len(nodes)} nodes")
    for node in nodes:
        typer.echo(f"{node.node_type:8} {node.file_path}::{node.full_name}")


@app.command("lsp")
def lsp_command(
    project_root: Annotated[Path, PROJECT_ROOT_ARG] = Path("."),
    config_path: Annotated[Path | None, CONFIG_ARG] = None,
    log_level: Annotated[str, LOG_LEVEL_ARG] = "INFO",
) -> None:
    """Start the LSP server standalone using a shared Remora sqlite database."""
    _configure_logging(log_level, lsp_mode=True)
    logger = logging.getLogger(__name__)

    project_root = project_root.resolve()
    config = load_config(config_path)
    db_path = project_root / config.workspace_root / "remora.db"
    if not db_path.exists():
        logger.error("Database not found at %s. Is 'remora start' running?", db_path)
        raise typer.Exit(code=1)

    lsp_server = create_lsp_server_standalone(db_path)
    logger.info("Starting standalone LSP server on stdin/stdout")
    lsp_server.start_io()


async def _start(
    *,
    project_root: Path,
    config_path: Path | None,
    port: int,
    no_web: bool,
    bind: str = "127.0.0.1",
    run_seconds: float = 0.0,
    log_events: bool = False,
    lsp: bool = False,
) -> None:
    project_root = project_root.resolve()
    config = load_config(config_path)
    lifecycle = RemoraLifecycle(
        config=config,
        project_root=project_root,
        bind=bind,
        port=port,
        no_web=no_web,
        log_events=log_events,
        lsp=lsp,
        configure_file_logging=_configure_file_logging,
    )
    await lifecycle.start()

    try:
        await lifecycle.run(run_seconds=run_seconds)
    finally:
        await lifecycle.shutdown()


async def _discover(
    *,
    project_root: Path,
    config_path: Path | None,
) -> list[CSTNode]:
    project_root = project_root.resolve()
    config = load_config(config_path)
    discovery_paths = resolve_discovery_paths(config, project_root)
    query_paths = resolve_query_paths(config, project_root)

    return discover_nodes(
        discovery_paths,
        language_map=config.language_map,
        query_paths=query_paths,
        languages=list(config.discovery_languages) if config.discovery_languages else None,
        ignore_patterns=config.workspace_ignore_patterns,
    )


def main() -> None:
    """CLI entrypoint used by `python -m remora` and script wrappers."""
    app(prog_name="remora")


def _configure_logging(level_name: str, *, lsp_mode: bool = False) -> None:
    level = getattr(logging, level_name.upper(), None)
    if not isinstance(level, int):
        raise typer.BadParameter(f"Invalid log level: {level_name}")
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    if root_logger.handlers:
        return

    stream = sys.stderr if lsp_mode else sys.stdout
    stream_handler = logging.StreamHandler(stream)
    stream_handler.addFilter(_ContextFilter())
    log_format = (
        "%(asctime)s %(levelname)s %(name)s "
        "[%(node_id)s:%(turn)s %(correlation_id)s]: %(message)s"
    )
    stream_handler.setFormatter(
        logging.Formatter(log_format)
    )
    root_logger.addHandler(stream_handler)


def _configure_file_logging(log_path: Path) -> None:
    root_logger = logging.getLogger()
    resolved_path = log_path.resolve()
    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler):
            try:
                if Path(handler.baseFilename).resolve() == resolved_path:
                    return
            except OSError:
                continue

    file_handler = RotatingFileHandler(
        filename=log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.addFilter(_ContextFilter())
    file_handler.setLevel(root_logger.level)
    log_format = (
        "%(asctime)s %(levelname)s %(name)s "
        "[%(node_id)s:%(turn)s %(correlation_id)s]: %(message)s"
    )
    file_handler.setFormatter(
        logging.Formatter(log_format)
    )
    root_logger.addHandler(file_handler)

if __name__ == "__main__":
    main()
