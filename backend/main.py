"""
RepoBot API — FastAPI server with WebSocket progress streaming.
"""

import asyncio
import json
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from orchestrator import start_analysis, get_job, list_jobs, subscribe, unsubscribe

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


@app.post("/api/analyze")
async def analyze(repo_path: str = Query(..., description="Absolute path to git repo")):
    if not os.path.isdir(repo_path):
        return {"error": f"Directory not found: {repo_path}"}
    job_id = await start_analysis(repo_path)
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
    uvicorn.run(app, host="0.0.0.0", port=8877)
