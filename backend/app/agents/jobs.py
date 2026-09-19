"""Analyses run as background jobs.

    job = submit(document_id, filename)   # returns at once
    get_job(job.id)                       # the browser polls this for progress

An analysis takes minutes, far too long to hold one HTTP request open, so
the upload endpoint only queues a job and returns its id.

- One worker thread runs jobs one at a time: every analysis shares Groq's
  per-minute limits, so running two at once would only slow both down.
- Progress comes from the graph's "custom" stream (the messages agents send
  through their writer); each job keeps them, plus a status per step.
- Each agent's output is saved as it finishes (see graph.py), and a
  finished job writes analysis.json. Finished analyses therefore survive a
  server restart; queued or running jobs don't (they live in memory), but
  re-submitting the document reuses every agent output already saved.
"""
import json
import logging
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.agents.graph import build_graph
from app.config import IPO_DATA_DIR
from app.drhp.parser import document_folder, load_parsed, load_result, save_result
from app.drhp.sections import OfferDocumentError

logger = logging.getLogger(__name__)

# The pipeline's steps, in the order the progress UI shows them
STEPS = ["parse", "index", "risk", "financial", "legal", "business", "offer", "score", "synthesis"]
# Each agent's saved output, by the state key it writes
RESULT_KEYS = ["risk", "financial", "legal", "business", "offer", "score", "report"]
STEP_STATUS = {"started": "running", "progress": "running", "waiting": "running", "done": "done", "failed": "failed"}


@dataclass
class Job:
    id: str
    document_id: str
    filename: str
    status: str = "queued"  # queued -> running -> done | failed
    steps: dict[str, str] = field(default_factory=lambda: {step: "waiting" for step in STEPS})
    events: list[dict] = field(default_factory=list)  # every progress message, oldest first
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None


_jobs: dict[str, Job] = {}
_lock = threading.Lock()
_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")
_graph = build_graph()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def document_pdf(doc_id: str) -> Path | None:
    """The uploaded PDF kept in the document's folder (under its original
    name, which the document id is partly made from)."""
    pdfs = sorted(document_folder(doc_id).glob("*.pdf")) + sorted(document_folder(doc_id).glob("*.PDF"))
    return pdfs[0] if pdfs else None


def _record(job: Job, event: dict) -> None:
    job.events.append({**event, "at": round(time.time() - job.created_at, 1)})
    if event.get("agent") in job.steps:
        job.steps[event["agent"]] = STEP_STATUS.get(event.get("event"), "running")


def _save_analysis(job: Job, final: dict) -> None:
    """analysis.json: what the list of past analyses shows."""
    save_result(job.document_id, "score", final["score"])
    summary = {
        "document_id": job.document_id,
        "filename": job.filename,
        "page_count": final["parsed"]["page_count"],
        "finished_at": _now(),
        "score": final["score"]["score"],
        "rating": final["score"]["rating"],
        "agents": {key: (final.get(key) or {}).get("status") for key in RESULT_KEYS if key != "score"},
    }
    path = document_folder(job.document_id) / "analysis.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


def _run(job: Job) -> None:
    job.status = "running"
    try:
        final = None
        stream = _graph.stream({"file_path": str(document_pdf(job.document_id))},
                               stream_mode=["custom", "values"])
        for mode, chunk in stream:
            if mode == "custom":
                _record(job, chunk)
            else:
                final = chunk
        _save_analysis(job, final)
        job.status = "done"
    except OfferDocumentError as exc:
        # Not a DRHP / RHP: nothing worth keeping
        job.status, job.error = "failed", str(exc)
        shutil.rmtree(document_folder(job.document_id), ignore_errors=True)
    except Exception as exc:  # a bug or an outage: keep what finished, so a retry resumes
        logger.exception("Analysis %s failed", job.id)
        job.status, job.error = "failed", f"The analysis stopped unexpectedly: {exc}"
    finally:
        job.finished_at = time.time()
        for step, status in job.steps.items():
            if job.status == "failed" and status == "running":
                job.steps[step] = "failed"


def active_job(doc_id: str) -> Job | None:
    with _lock:
        return next((j for j in _jobs.values()
                     if j.document_id == doc_id and j.status in ("queued", "running")), None)


def submit(doc_id: str, filename: str) -> Job:
    """Queue an analysis of a document already saved in its folder. If one
    is already queued or running for it, that job is returned instead."""
    existing = active_job(doc_id)
    if existing:
        return existing
    job = Job(id=uuid.uuid4().hex[:12], document_id=doc_id, filename=filename)
    with _lock:
        _jobs[job.id] = job
    _worker.submit(_run, job)
    return job


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def job_view(job: Job, after: int = 0) -> dict:
    """A job for the API: events after the first `after`, so polling
    doesn't resend the whole history each time."""
    view = asdict(job)
    view["events"] = job.events[after:]
    view["event_count"] = len(job.events)
    view["queue_position"] = sum(1 for j in _jobs.values() if j.status == "queued" and j.created_at < job.created_at)
    return view


def list_analyses() -> list[dict]:
    """Every finished analysis, newest first."""
    analyses = []
    for path in Path(IPO_DATA_DIR).glob("*/analysis.json"):
        analyses.append(json.loads(path.read_text(encoding="utf-8")))
    return sorted(analyses, key=lambda a: a["finished_at"], reverse=True)


def load_analysis(doc_id: str) -> dict | None:
    """A finished analysis: its summary, the document's outline, and every
    agent's output."""
    path = document_folder(doc_id) / "analysis.json"
    if not path.exists():
        return None
    parsed = load_parsed(doc_id)
    first = parsed["sections"][0]
    return {
        **json.loads(path.read_text(encoding="utf-8")),
        # Citations use the page numbers printed in the document; a PDF
        # viewer counts from the cover. Printed page p is PDF page p + offset + 1.
        "page_offset": first["start_index"] - first["start_page"],
        "sections": [{"title": s["title"], "key": s["key"], "start_page": s["start_page"], "end_page": s["end_page"]}
                     for s in parsed["sections"]],
        "results": {key: load_result(doc_id, key) for key in RESULT_KEYS},
    }


def clear_results(doc_id: str) -> None:
    """Forget saved agent outputs, so the next analysis starts afresh
    (the parsed data and search index are kept)."""
    shutil.rmtree(document_folder(doc_id) / "results", ignore_errors=True)
    (document_folder(doc_id) / "analysis.json").unlink(missing_ok=True)


def delete_analysis(doc_id: str) -> bool:
    """Delete everything saved for a document. False if there's nothing."""
    folder = document_folder(doc_id)
    if not folder.exists():
        return False
    shutil.rmtree(folder)
    return True
