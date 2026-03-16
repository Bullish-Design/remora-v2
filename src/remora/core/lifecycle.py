"""Runtime lifecycle orchestration for Remora services."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

import uvicorn

from remora.core.config import Config
from remora.core.db import open_database
from remora.core.events import Event
from remora.core.services import RuntimeServices
from remora.lsp import create_lsp_server
from remora.web.server import create_app

logger = logging.getLogger(__name__)


class RemoraLifecycle:
    """Own startup, run loop, and ordered shutdown for runtime services."""

    def __init__(
        self,
        *,
        config: Config,
        project_root: Path,
        bind: str,
        port: int,
        no_web: bool,
        log_events: bool,
        lsp: bool,
        configure_file_logging: Any,
    ) -> None:
        self._config = config
        self._project_root = project_root.resolve()
        self._bind = bind
        self._port = port
        self._no_web = no_web
        self._log_events = log_events
        self._lsp = lsp
        self._configure_file_logging = configure_file_logging

        self._services: RuntimeServices | None = None
        self._tasks: list[asyncio.Task] = []
        self._web_server: uvicorn.Server | None = None
        self._lsp_server: Any | None = None
        self._started = False

    async def start(self) -> None:
        """Initialize services and launch background runtime tasks."""
        db_path = self._project_root / self._config.workspace_root / "remora.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        log_path = db_path.parent / "remora.log"
        self._configure_file_logging(log_path)

        db = await open_database(db_path)
        services = RuntimeServices(self._config, self._project_root, db)
        self._services = services

        logger.info("Logging to %s", log_path)
        logger.info("Initializing runtime services")
        await services.initialize()
        if services.reconciler is None:
            raise RuntimeError("RuntimeServices.initialize() did not set reconciler")
        if services.runner is None:
            raise RuntimeError("RuntimeServices.initialize() did not set runner")

        if self._log_events:
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
        self._tasks = [runner_task, reconciler_task]

        if not self._no_web:
            web_app = create_app(
                services.event_store,
                services.node_store,
                services.event_bus,
                metrics=services.metrics,
                actor_pool=services.runner,
                workspace_service=services.workspace_service,
            )
            logger.info("Starting web server on %s:%d", self._bind, self._port)
            web_config = uvicorn.Config(
                web_app,
                host=self._bind,
                port=self._port,
                log_level="warning",
                access_log=False,
            )
            self._web_server = uvicorn.Server(web_config)
            self._tasks.append(asyncio.create_task(self._web_server.serve(), name="remora-web"))
        else:
            logger.info("Web server disabled (--no-web)")

        if self._lsp:
            self._lsp_server = create_lsp_server(services.node_store, services.event_store)
            logger.info("Starting LSP server on stdin/stdout")
            lsp_task = asyncio.create_task(
                asyncio.to_thread(self._lsp_server.start_io),
                name="remora-lsp",
            )
            self._tasks.append(lsp_task)

        self._started = True

    async def run(self, *, run_seconds: float = 0.0) -> None:
        """Run the lifecycle until timeout or until one task exits unexpectedly."""
        if not self._started:
            raise RuntimeError("RemoraLifecycle.start() must be called before run()")

        if run_seconds > 0:
            await asyncio.sleep(run_seconds)
        else:
            await asyncio.gather(*self._tasks)

    async def shutdown(self) -> None:
        """Stop tasks and close services in a deterministic order."""
        services = self._services
        if services is None:
            self._started = False
            return

        try:
            if services.reconciler is not None:
                services.reconciler.stop()
            if services.runner is not None:
                try:
                    await asyncio.wait_for(services.runner.stop_and_wait(), timeout=10.0)
                except TimeoutError:
                    logger.warning("Actor pool did not drain within 10s, forcing shutdown")

            reconciler_stop_task = (
                services.reconciler.stop_task
                if services.reconciler is not None
                else None
            )
            if self._web_server is not None:
                self._web_server.should_exit = True

            await services.close()

            for task in self._tasks:
                if not task.done():
                    task.cancel()

            if self._lsp_server is not None:
                try:
                    await asyncio.to_thread(self._lsp_server.shutdown)
                except Exception as exc:  # pragma: no cover - best effort
                    logger.warning("LSP shutdown failed: %s", exc)
                try:
                    await asyncio.to_thread(self._lsp_server.exit)
                except Exception:
                    pass

            if reconciler_stop_task is not None and reconciler_stop_task not in self._tasks:
                self._tasks.append(reconciler_stop_task)
            await asyncio.gather(*self._tasks, return_exceptions=True)
        finally:
            self._started = False


__all__ = ["RemoraLifecycle"]
