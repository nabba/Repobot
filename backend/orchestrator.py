"""
Orchestrator — manages parallel agent execution, tracks progress,
assembles the final report.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from agents import AGENTS, Status, AgentResult, write_summary
from repo_scanner import scan_repo


@dataclass
class AnalysisJob:
    job_id: str
    repo_path: str  # display path (URL or local)
    scan_path: str = ""  # actual filesystem path to scan
    status: str = "scanning"
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    agents: dict[str, AgentResult] = field(default_factory=dict)
    report: str = ""
    error: str = ""
    repo_stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        elapsed = (self.finished_at or time.time()) - self.started_at
        return {
            "job_id": self.job_id,
            "repo_path": self.repo_path,
            "status": self.status,
            "elapsed_seconds": round(elapsed, 1),
            "repo_stats": self.repo_stats,
            "agents": {
                name: {
                    "status": a.status.value,
                    "progress": a.progress,
                }
                for name, a in self.agents.items()
            },
            "report_ready": bool(self.report),
            "error": self.error,
        }


# In-memory job store
_jobs: dict[str, AnalysisJob] = {}
_subscribers: dict[str, list[asyncio.Queue]] = {}


def get_job(job_id: str) -> AnalysisJob | None:
    return _jobs.get(job_id)


def list_jobs() -> list[dict]:
    return [j.to_dict() for j in _jobs.values()]


def subscribe(job_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.setdefault(job_id, []).append(q)
    return q


def unsubscribe(job_id: str, q: asyncio.Queue):
    if job_id in _subscribers:
        _subscribers[job_id] = [x for x in _subscribers[job_id] if x is not q]


async def _notify(job_id: str, event: dict):
    for q in _subscribers.get(job_id, []):
        await q.put(event)


async def start_analysis(scan_path: str, display_path: str | None = None) -> str:
    job_id = uuid.uuid4().hex[:8]
    job = AnalysisJob(job_id=job_id, repo_path=display_path or scan_path, scan_path=scan_path)

    # Initialize agent results
    for name in AGENTS:
        _, label = AGENTS[name]
        job.agents[name] = AgentResult(agent_name=label)

    # Add summary agent
    job.agents["summary"] = AgentResult(agent_name="Executive Summary")

    _jobs[job_id] = job

    # Launch analysis in background
    asyncio.create_task(_run_analysis(job))
    return job_id


async def _run_analysis(job: AnalysisJob):
    job_id = job.job_id

    # Phase 1: Scan repo
    try:
        await _notify(job_id, {"type": "status", "status": "scanning"})
        scan = scan_repo(job.scan_path)
        context = scan["context"]
        job.repo_stats = scan["stats"]
        await _notify(job_id, {
            "type": "scanned",
            "stats": scan["stats"],
            "tree_preview": scan["tree"][:2000],
        })
    except Exception as e:
        job.status = "error"
        job.error = str(e)
        await _notify(job_id, {"type": "error", "error": str(e)})
        return

    # Phase 2: Run all agents in parallel
    job.status = "analyzing"
    await _notify(job_id, {"type": "status", "status": "analyzing"})

    async def run_agent(name: str):
        fn, label = AGENTS[name]
        result = job.agents[name]
        result.status = Status.RUNNING
        await _notify(job_id, {
            "type": "agent_update",
            "agent": name,
            "status": "running",
            "progress": "Starting...",
        })

        async def on_progress(msg: str):
            result.progress = msg
            await _notify(job_id, {
                "type": "agent_update",
                "agent": name,
                "status": "running",
                "progress": msg,
            })

        try:
            output = await fn(context, on_progress)
            result.output = output
            result.status = Status.DONE
            result.progress = "Complete"
            await _notify(job_id, {
                "type": "agent_update",
                "agent": name,
                "status": "done",
                "progress": "Complete",
            })
        except Exception as e:
            result.status = Status.ERROR
            result.progress = f"Error: {e}"
            result.output = f"*Analysis failed: {e}*"
            await _notify(job_id, {
                "type": "agent_update",
                "agent": name,
                "status": "error",
                "progress": str(e),
            })

    await asyncio.gather(*[run_agent(name) for name in AGENTS])

    # Phase 3: Write summary
    job.status = "writing"
    await _notify(job_id, {"type": "status", "status": "writing"})
    summary_result = job.agents["summary"]
    summary_result.status = Status.RUNNING

    async def on_summary_progress(msg: str):
        summary_result.progress = msg
        await _notify(job_id, {
            "type": "agent_update",
            "agent": "summary",
            "status": "running",
            "progress": msg,
        })

    try:
        sections = {
            AGENTS[name][1]: job.agents[name].output
            for name in AGENTS
            if job.agents[name].status == Status.DONE
        }
        summary_output = await write_summary(sections, on_summary_progress)
        summary_result.output = summary_output
        summary_result.status = Status.DONE
    except Exception as e:
        summary_result.output = ""
        summary_result.status = Status.ERROR
        summary_result.progress = f"Error: {e}"

    # Phase 4: Assemble report
    job.status = "assembling"
    report_parts = [
        f"# System Documentation: {job.repo_path}\n",
        f"*Generated by RepoBot — multi-agent repository analyzer*\n",
        "---\n",
    ]

    if summary_result.output:
        report_parts.append(f"## Executive Summary\n\n{summary_result.output}\n\n---\n")

    for name in AGENTS:
        _, label = AGENTS[name]
        agent_out = job.agents[name].output
        if agent_out:
            report_parts.append(f"{agent_out}\n\n---\n")

    job.report = "\n".join(report_parts)
    job.status = "done"
    job.finished_at = time.time()
    await _notify(job_id, {"type": "status", "status": "done"})
