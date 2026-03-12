"""Projection from discovered CST nodes into persisted CodeNodes."""

from __future__ import annotations

import hashlib
from pathlib import Path

from remora.code.discovery import CSTNode
from remora.core.config import Config
from remora.core.graph import NodeStore
from remora.core.node import CodeNode
from remora.core.workspace import CairnWorkspaceService


async def project_nodes(
    cst_nodes: list[CSTNode],
    node_store: NodeStore,
    workspace_service: CairnWorkspaceService,
    config: Config,
) -> list[CodeNode]:
    """Project CSTNodes into CodeNodes and provision bundles for new nodes."""
    results: list[CodeNode] = []
    bundle_root = Path(config.bundle_root)

    for cst in cst_nodes:
        source_hash = hashlib.sha256(cst.text.encode("utf-8")).hexdigest()
        existing = await node_store.get_node(cst.node_id)
        if existing is not None and existing.source_hash == source_hash:
            results.append(existing)
            continue

        mapped_bundle = config.bundle_mapping.get(cst.node_type)
        code_node = CodeNode(
            node_id=cst.node_id,
            node_type=cst.node_type,
            name=cst.name,
            full_name=cst.full_name,
            file_path=cst.file_path,
            start_line=cst.start_line,
            end_line=cst.end_line,
            start_byte=cst.start_byte,
            end_byte=cst.end_byte,
            source_code=cst.text,
            source_hash=source_hash,
            parent_id=cst.parent_id,
            caller_ids=existing.caller_ids if existing else [],
            callee_ids=existing.callee_ids if existing else [],
            status=existing.status if existing else "idle",
            bundle_name=(
                mapped_bundle
                if mapped_bundle is not None
                else (existing.bundle_name if existing else None)
            ),
        )

        await node_store.upsert_node(code_node)

        if existing is None:
            template_dirs = [bundle_root / "system"]
            if mapped_bundle:
                template_dirs.append(bundle_root / mapped_bundle)
            await workspace_service.provision_bundle(cst.node_id, template_dirs)

        results.append(code_node)

    return results


__all__ = ["project_nodes"]
