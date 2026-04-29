"""
Recording browsing endpoints.

GET /api/recordings                         — list all completed recordings
GET /api/recordings/{session_id}/metadata   — metadata.json content
GET /api/recordings/{session_id}/telemetry  — telemetry.jsonl stream
"""

import json
import pathlib
from typing import Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from server.config.config import RECORDINGS_DIR

router = APIRouter(prefix="/api/recordings")


def _recordings_root() -> pathlib.Path:
    return pathlib.Path(RECORDINGS_DIR)


# ---------------------------------------------------------------------------
# List recordings
# ---------------------------------------------------------------------------

@router.get("")
async def list_recordings():
    """
    Scan RECORDINGS_DIR for subdirectories that contain metadata.json.
    Return a list of metadata summaries sorted by recorded_at descending.
    """
    root = _recordings_root()
    results = []

    if not root.exists():
        return results

    for subdir in root.iterdir():
        if not subdir.is_dir():
            continue
        meta_file = subdir / "metadata.json"
        if not meta_file.exists():
            continue
        try:
            with open(meta_file, encoding="utf-8") as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        results.append({
            "session_id":     subdir.name,
            "session_type":   meta.get("session_type"),
            "recorded_at":    meta.get("recorded_at") or meta.get("finished_at"),
            "finish_reason":  meta.get("finish_reason"),
            "teams":          meta.get("teams", []),
            "final_rankings": meta.get("final_rankings", []),
        })

    results.sort(key=lambda r: r.get("recorded_at") or "", reverse=True)
    return results


# ---------------------------------------------------------------------------
# Metadata for a single session
# ---------------------------------------------------------------------------

@router.get("/{session_id}/metadata")
async def get_metadata(session_id: str):
    """Return the raw metadata.json content for a completed recording."""
    meta_file = _recordings_root() / session_id / "metadata.json"
    if not meta_file.exists():
        raise HTTPException(status_code=404, detail="Recording not found")

    try:
        with open(meta_file, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Telemetry stream
# ---------------------------------------------------------------------------

@router.get("/{session_id}/telemetry")
async def get_telemetry(session_id: str):
    """
    Stream telemetry.jsonl as application/x-ndjson.

    Only available once metadata.json exists (recording is complete).
    Returns 404 if the recording is missing or still in progress.
    """
    session_dir    = _recordings_root() / session_id
    meta_file      = session_dir / "metadata.json"
    telemetry_file = session_dir / "telemetry.jsonl"

    if not meta_file.exists():
        raise HTTPException(
            status_code=404,
            detail="Recording not found or not yet complete",
        )
    if not telemetry_file.exists():
        raise HTTPException(status_code=404, detail="Telemetry file not found")

    def _iter_lines() -> Iterator[bytes]:
        with open(telemetry_file, "rb") as f:
            for line in f:
                yield line

    return StreamingResponse(
        _iter_lines(),
        media_type="application/x-ndjson",
    )
