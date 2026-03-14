"""Remora CLI entry point (Typer-based)."""

from __future__ import annotations

import asyncio
import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from remora.code.discovery import CSTNode
from remora.code.discovery import discover as discover_nodes
from remora.code.paths import resolve_discovery_paths, resolve_query_paths
from remora.core.config import load_config
from remora.core.db import AsyncDB
from remora.core.events import Event
from remora.core.services import RuntimeServices
from remora.lsp import create_lsp_server
from remora.web.server import create_app

app = typer.Typer(
    name="remora",
    help="Remora - event-driven graph agent runner.",
    no_args_is_help=True,
    add_completion=False,
)

PROJECT_ROOT_ARG = typer.Option(
    "--project-root",
    exists=True,
    file_okay=False,
    dir_okay=True,
)
CONFIG_ARG = typer.Option("--config")
PORT_ARG = typer.Option("--port", min=1, max=65535)
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
    no_web: Annotated[bool, NO_WEB_ARG] = False,
    run_seconds: Annotated[float, RUN_SECONDS_ARG] = 0.0,
    log_level: Annotated[str, LOG_LEVEL_ARG] = "INFO",
    log_events: Annotated[bool, LOG_EVENTS_ARG] = False,
    lsp: Annotated[bool, LSP_ARG] = False,
) -> None:
    """Start Remora components and run until interrupted."""
    _configure_logging(log_level)
    try:
        asyncio.run(
            _start(
                project_root=project_root,
                config_path=config_path,
                port=port,
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


async def _start(
    *,
    project_root: Path,
    config_path: Path | None,
    port: int,
    no_web: bool,
    run_seconds: float = 0.0,
    log_events: bool = False,
    lsp: bool = False,
) -> None:
    logger = logging.getLogger(__name__)
    project_root = project_root.resolve()
    config = load_config(config_path)

    db_path = project_root / config.workspace_root / "remora.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = db_path.parent / "remora.log"
    _configure_file_logging(log_path)
    db = AsyncDB.from_path(db_path)
    services = RuntimeServices(config, project_root, db)
    logger.info("Logging to %s", log_path)
    logger.info("Initializing runtime services")
    await services.initialize()
    assert services.reconciler is not None
    assert services.runner is not None

    if log_events:
        event_logger = logging.getLogger("remora.events")

        def log_event(event: Event) -> None:
            event_logger.info(
                "event=%s corr=%s agent=%s from=%s to=%s path=%s",
                event.event_type,
                event.correlation_id or "-",
                getattr(event, "agent_id", "-"),
                getattr(event, "from_agent", "-"),
                getattr(event, "to_agent", "-"),
                getattr(event, "path", None) or getattr(event, "file_path", "-"),
            )

        services.event_bus.subscribe_all(log_event)
        logger.info("Event activity logging enabled")

    logger.info("Starting full discovery scan")
    scan_started = time.perf_counter()
    scanned_nodes = await services.reconciler.full_scan()
    logger.info(
        "Discovery complete: nodes=%d duration=%.2fs",
        len(scanned_nodes),
        time.perf_counter() - scan_started,
    )

    runner_task = asyncio.create_task(services.runner.run_forever(), name="remora-runner")
    reconciler_task = asyncio.create_task(
        services.reconciler.run_forever(),
        name="remora-reconciler",
    )
    tasks: list[asyncio.Task] = [runner_task, reconciler_task]
    web_server: uvicorn.Server | None = None
    lsp_server = None
    lsp_task: asyncio.Task | None = None

    if not no_web:
        web_app = create_app(
            services.event_store,
            services.node_store,
            services.event_bus,
            project_root=project_root,
        )
        logger.info("Starting web server on 127.0.0.1:%d", port)
        web_config = uvicorn.Config(
            web_app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
        )
        web_server = uvicorn.Server(web_config)
        tasks.append(asyncio.create_task(web_server.serve(), name="remora-web"))
    else:
        logger.info("Web server disabled (--no-web)")

    if lsp:
        lsp_server = create_lsp_server(services.node_store, services.event_store)
        logger.info("Starting LSP server on stdin/stdout")
        lsp_task = asyncio.create_task(
            asyncio.to_thread(lsp_server.start_io),
            name="remora-lsp",
        )
        tasks.append(lsp_task)

    try:
        if run_seconds > 0:
            await asyncio.sleep(run_seconds)
        else:
            await asyncio.gather(*tasks)
    finally:
        await services.close()
        reconciler_stop_task = (
            services.reconciler.stop_task
            if services.reconciler is not None
            else None
        )
        if web_server is not None:
            web_server.should_exit = True
        for task in tasks:
            if not task.done():
                task.cancel()
        if lsp_server is not None:
            try:
                await asyncio.to_thread(lsp_server.shutdown)
            except Exception as exc:  # pragma: no cover - best effort
                logger.warning("LSP shutdown failed: %s", exc)
            try:
                await asyncio.to_thread(lsp_server.exit)
            except Exception:
                pass
        if reconciler_stop_task is not None and reconciler_stop_task not in tasks:
            tasks.append(reconciler_stop_task)
        await asyncio.gather(*tasks, return_exceptions=True)


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


def _configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), None)
    if not isinstance(level, int):
        raise typer.BadParameter(f"Invalid log level: {level_name}")
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    if root_logger.handlers:
        return

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
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
    file_handler.setLevel(root_logger.level)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root_logger.addHandler(file_handler)

if __name__ == "__main__":
    main()
