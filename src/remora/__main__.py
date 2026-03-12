"""Remora CLI entry point (Typer-based)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from remora.code.discovery import CSTNode
from remora.code.discovery import discover as discover_nodes
from remora.code.reconciler import FileReconciler
from remora.core.config import load_config
from remora.core.db import AsyncDB
from remora.core.events import EventBus, EventStore, SubscriptionRegistry, TriggerDispatcher
from remora.core.graph import NodeStore
from remora.core.runner import AgentRunner
from remora.core.workspace import CairnWorkspaceService
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


@app.command("start")
def start_command(
    project_root: Annotated[Path, PROJECT_ROOT_ARG] = Path("."),
    config_path: Annotated[Path | None, CONFIG_ARG] = None,
    port: Annotated[int, PORT_ARG] = 8080,
    no_web: Annotated[bool, NO_WEB_ARG] = False,
    run_seconds: Annotated[float, RUN_SECONDS_ARG] = 0.0,
) -> None:
    """Start Remora components and run until interrupted."""
    try:
        asyncio.run(
            _start(
                project_root=project_root,
                config_path=config_path,
                port=port,
                no_web=no_web,
                run_seconds=run_seconds,
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
) -> None:
    project_root = project_root.resolve()
    config = load_config(config_path)

    db_path = project_root / config.swarm_root / "remora.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = AsyncDB.from_path(db_path)

    event_bus = EventBus()
    node_store = NodeStore(db)
    await node_store.create_tables()

    subscriptions = SubscriptionRegistry(db)
    dispatcher = TriggerDispatcher(subscriptions)
    event_store = EventStore(
        db=db,
        event_bus=event_bus,
        dispatcher=dispatcher,
    )
    await event_store.create_tables()

    workspace_service = CairnWorkspaceService(config, project_root)
    await workspace_service.initialize()

    reconciler = FileReconciler(
        config,
        node_store,
        event_store,
        workspace_service,
        project_root,
    )
    logging.info("Starting code discovery...")
    await reconciler.full_scan()

    runner = AgentRunner(event_store, node_store, workspace_service, config)
    runner_task = asyncio.create_task(runner.run_forever(), name="remora-runner")
    reconciler_task = asyncio.create_task(
        reconciler.run_forever(),
        name="remora-reconciler",
    )
    tasks: list[asyncio.Task] = [runner_task, reconciler_task]
    web_server: uvicorn.Server | None = None

    if not no_web:
        web_app = create_app(
            event_store,
            node_store,
            event_bus,
            project_root=project_root,
        )
        web_config = uvicorn.Config(
            web_app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
        )
        web_server = uvicorn.Server(web_config)
        tasks.append(asyncio.create_task(web_server.serve(), name="remora-web"))

    try:
        if run_seconds > 0:
            await asyncio.sleep(run_seconds)
        else:
            await asyncio.gather(*tasks)
    finally:
        reconciler.stop()
        runner.stop()
        if web_server is not None:
            web_server.should_exit = True
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await workspace_service.close()
        db.close()


async def _discover(
    *,
    project_root: Path,
    config_path: Path | None,
) -> list[CSTNode]:
    project_root = project_root.resolve()
    config = load_config(config_path)
    discovery_paths: list[Path] = []
    for configured_path in config.discovery_paths:
        candidate = Path(configured_path)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        discovery_paths.append(candidate)
    query_paths: list[Path] = []
    for configured_query_path in config.query_paths:
        query_candidate = Path(configured_query_path)
        if not query_candidate.is_absolute():
            query_candidate = project_root / query_candidate
        query_paths.append(query_candidate)

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

if __name__ == "__main__":
    main()
