"""Read-only drift scan across every app workspace in this OpenSwarm install.

Grades each sibling workspace against the six fixes this template carries. Nothing here writes,
executes, or otherwise touches another app: it reads text files and stat()s one marker.
"""

import json
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List

from fastapi.responses import JSONResponse
from typeguard import typechecked
from swarm_debug import debug

from backend.config.Apps import SubApp
from backend.apps.drift.checks import P_CHECKS, p_grade_workspace


@asynccontextmanager
async def drift_lifespan():
    debug("drift_lifespan START")
    yield
    debug("drift_lifespan END")


drift = SubApp("drift", drift_lifespan)

# This file lives at <ws>/backend/apps/drift/drift.py, so four dirnames up is the workspace and
# five is outputs_workspace/ — the directory holding every app in the install. Deriving it from
# __file__ rather than hardcoding a home path keeps the scan correct on any machine.
P_THIS_WORKSPACE = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)
P_WORKSPACE_ROOT = os.path.dirname(P_THIS_WORKSPACE)


@typechecked
def p_workspace_name(ws: str) -> str:
    """The app's display name from meta.json, falling back to the workspace id."""
    try:
        with open(os.path.join(ws, "meta.json"), "r", encoding="utf-8") as f:
            meta = json.load(f)
        name = meta.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    except (OSError, json.JSONDecodeError):
        pass
    # No meta.json at all. Showing a bare 32-char hex id reads as corruption; say what it is.
    return f"(unnamed workspace {os.path.basename(ws)[:8]})"


@typechecked
def p_is_workspace(path: str) -> bool:
    """An app workspace, not some unrelated directory that wandered in."""
    if not os.path.isdir(path):
        return False
    return os.path.isdir(os.path.join(path, "frontend")) or os.path.isfile(
        os.path.join(path, "meta.json")
    )


@typechecked
def p_scan() -> List[Dict[str, Any]]:
    apps: List[Dict[str, Any]] = []
    try:
        entries = sorted(os.listdir(P_WORKSPACE_ROOT))
    except OSError:
        return apps

    for entry in entries:
        ws = os.path.join(P_WORKSPACE_ROOT, entry)
        if not p_is_workspace(ws):
            continue
        graded = p_grade_workspace(ws)
        apps.append({
            "id": entry,
            "name": p_workspace_name(ws),
            "path": ws,
            "is_self": os.path.realpath(ws) == os.path.realpath(P_THIS_WORKSPACE),
            "has_backend": os.path.isdir(os.path.join(ws, "backend")),
            "failed": graded["failed"],
            "applicable": graded["applicable"],
            "passed": graded["passed"],
            "checks": graded["checks"],
        })

    # Worst first: the point of the page is triage, not a directory listing.
    apps.sort(key=lambda a: (-int(a["failed"]), str(a["name"]).lower()))
    return apps


# ##################################### Drift Endpoints # #####################################

@drift.router.get("/scan")
@typechecked
async def scan() -> JSONResponse:
    apps = p_scan()
    clean = sum(1 for a in apps if a["failed"] == 0)
    debug(f"drift scan: {len(apps)} workspaces, {clean} clean")
    return JSONResponse({
        "root": P_WORKSPACE_ROOT,
        "total": len(apps),
        "clean": clean,
        "drifted": len(apps) - clean,
        "checks": [
            {"id": c["id"], "label": c["label"], "severity": c["severity"], "fix": c["fix"]}
            for c in P_CHECKS
        ],
        "apps": apps,
    })
