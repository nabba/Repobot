"""
RepoBot API — FastAPI server with WebSocket progress streaming.
"""

import asyncio
import json
import os
import re
import shutil
import tempfile
import subprocess

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from orchestrator import start_analysis, get_job, list_jobs, subscribe, unsubscribe

GITHUB_URL_RE = re.compile(
    r"^https?://github\.com/[\w.\-]+/[\w.\-]+/?$"
    r"|^git@github\.com:[\w.\-]+/[\w.\-]+\.git$"
    r"|^https?://github\.com/[\w.\-]+/[\w.\-]+\.git$"
)
CLONE_DIR = os.path.join(tempfile.gettempdir(), "repobot_clones")
os.makedirs(CLONE_DIR, exist_ok=True)


def _is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://") or s.startswith("git@")


async def clone_repo(url: str) -> str:
    """Shallow-clone a git repo and return the local path."""
    # Derive folder name from URL
    name = url.rstrip("/").split("/")[-1].removesuffix(".git")
    dest = os.path.join(CLONE_DIR, name)
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    proc = await asyncio.create_subprocess_exec(
        "git", "clone", "--depth", "1", url, dest,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"git clone failed: {stderr.decode().strip()}")
    return dest

app = FastAPI(title="RepoBot", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


HOST_MOUNT = os.environ.get("HOST_MOUNT", "")  # e.g. "/host" in Docker


@app.post("/api/analyze")
async def analyze(repo_path: str = Query(..., description="Absolute path or GitHub URL")):
    if _is_url(repo_path):
        try:
            scan_path = await clone_repo(repo_path)
        except RuntimeError as e:
            return {"error": str(e)}
        display_path = repo_path
    else:
        # Local path — in Docker, host filesystem is mounted at /host
        scan_path = HOST_MOUNT + repo_path if HOST_MOUNT else repo_path
        if not os.path.isdir(scan_path):
            return {"error": f"Directory not found: {repo_path}"}
        display_path = repo_path
    job_id = await start_analysis(scan_path, display_path)
    return {"job_id": job_id}


@app.get("/api/jobs")
async def jobs():
    return list_jobs()


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        return {"error": "Job not found"}
    return job.to_dict()


@app.get("/api/jobs/{job_id}/report")
async def download_report(job_id: str):
    job = get_job(job_id)
    if not job or not job.report:
        return {"error": "Report not ready"}
    return PlainTextResponse(
        content=job.report,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="report-{job_id}.md"'},
    )


@app.get("/api/jobs/{job_id}/report/preview")
async def preview_report(job_id: str):
    job = get_job(job_id)
    if not job or not job.report:
        return {"error": "Report not ready"}
    return PlainTextResponse(content=job.report, media_type="text/markdown")


@app.websocket("/ws/{job_id}")
async def websocket_progress(websocket: WebSocket, job_id: str):
    await websocket.accept()
    job = get_job(job_id)
    if not job:
        await websocket.send_json({"type": "error", "error": "Job not found"})
        await websocket.close()
        return

    # Send current state
    await websocket.send_json({"type": "snapshot", **job.to_dict()})

    if job.status == "done":
        await websocket.close()
        return

    q = subscribe(job_id)
    try:
        while True:
            event = await q.get()
            await websocket.send_json(event)
            if event.get("status") == "done" or event.get("type") == "error":
                break
    except WebSocketDisconnect:
        pass
    finally:
        unsubscribe(job_id, q)


if __name__ == "__main__":
    import uvicorn

    cert = os.path.join(os.path.dirname(__file__), "cert.pem")
    key = os.path.join(os.path.dirname(__file__), "key.pem")

    uvicorn.run(app, host="0.0.0.0", port=8877)
