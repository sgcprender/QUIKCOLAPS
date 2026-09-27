"""FastAPI routes for the demo app. One step runs at a time (jobs.JOBS); the browser polls the log."""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import projects, steps, viewer
from .jobs import JOBS, StepError, build_tools
from .projects import STEPS, Project

AP = Path(__file__).resolve().parents[1]
WEB = AP / "web"

app = FastAPI(title="QUIKCOLAPS")
app.mount("/static", StaticFiles(directory=WEB / "app"), name="static")


@app.on_event("startup")
def _build() -> None:
    try:
        JOBS.start("", "build tools", build_tools)
    except RuntimeError:
        pass


@app.get("/")
def index():
    return FileResponse(WEB / "app" / "index.html")


def _p(pid: str) -> Project:
    try:
        return projects.get(pid)
    except KeyError:
        raise HTTPException(404, f"no project {pid}")


def _etabs_running() -> bool:
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ETABS.exe", "/NH"], capture_output=True, text=True, timeout=10).stdout
        return "ETABS.exe" in out
    except Exception:  # noqa: BLE001
        return False


@app.get("/api/etabs")
def etabs():
    return {"running": _etabs_running()}


@app.get("/api/projects")
def list_projects():
    return [p.summary() for p in projects.all_projects()]


class NewProject(BaseModel):
    model_path: str
    name: str | None = None


@app.post("/api/projects")
def new_project(body: NewProject):
    try:
        p, notes = projects.create(Path(body.model_path.strip().strip('"')), body.name or None)
    except (ValueError, OSError) as e:
        raise HTTPException(400, str(e))
    return {**p.summary(), "notes": notes}


@app.post("/api/pick-model")
def pick_model():
    """Native file dialog on this machine (the server runs locally)."""
    result = {}

    def ask():
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        result["path"] = filedialog.askopenfilename(title="Pick the ETABS model", filetypes=[("ETABS model", "*.edb *.EDB")])
        root.destroy()

    t = threading.Thread(target=ask)
    t.start()
    t.join(300)
    return {"path": result.get("path") or ""}


@app.delete("/api/projects/{pid}")
def remove_project(pid: str):
    projects.remove(pid)
    return {"removed": pid, "note": "removed from the list; no files were deleted"}


@app.get("/api/projects/{pid}")
def project(pid: str):
    p = _p(pid)
    return {**p.summary(), "steps": [{"n": n, "name": name, **p.step(n)} for n, name in STEPS],
            "files": sorted(x.name for x in p.folder.glob("*.json")),
            "strength_combos": p.state.get("strength_combos"), "notes": p.state.get("notes", []), "etabs": _etabs_running()}


@app.get("/api/projects/{pid}/file/{name}")
def project_file(pid: str, name: str):
    p = _p(pid)
    if "/" in name or "\\" in name or not name.endswith(".json"):
        raise HTTPException(400, "json files in the project folder only")
    data = p.load(name)
    if data is None:
        raise HTTPException(404, f"{name} not in {p.folder}")
    return JSONResponse(data)


@app.get("/api/projects/{pid}/viewer")
def project_viewer(pid: str):
    return viewer.build(_p(pid))


class RunStep(BaseModel):
    cached: bool = False


def _unlocked(p: Project, n: int) -> bool:
    return n == 0 or p.step(n - 1)["status"] == "done"


@app.post("/api/projects/{pid}/steps/{n}/run")
def run_step(pid: str, n: int, body: RunStep):
    p = _p(pid)
    if n not in steps.RUN:
        raise HTTPException(404, f"no step {n}")
    if not _unlocked(p, n):
        raise HTTPException(409, f"step {n} unlocks when step {n - 1} is done")
    name = STEPS[n][1]
    if body.cached:
        try:
            st = steps.cached(p, n)
        except StepError as e:
            raise HTTPException(409, str(e))
        p.set_step(n, "awaiting" if st == "awaiting" else "done", "from cached results", cached=True,
                   awaiting=steps.AWAITS.get(n) if st == "awaiting" else None)
        return {"status": p.step(n)["status"]}
    if not p.state.get("demo_ok_to_run", True):
        raise HTTPException(409, "this project is read-only")
    p.reset_after(n)
    p.set_step(n, "running", "")

    def fn(job):
        return steps.RUN[n](job, p)

    def done(job):
        if n in steps.AWAITS:
            p.set_step(n, "awaiting", job.result, awaiting=steps.AWAITS[n])
        else:
            p.set_step(n, "done", job.result)

    def fail(job):
        p.set_step(n, "failed", job.error)

    try:
        job = JOBS.start(pid, f"{n} {name}", fn, done, fail)
    except RuntimeError as e:
        p.set_step(n, "todo", "")
        raise HTTPException(409, str(e))
    return {"job": job.id}


class Approve(BaseModel):
    accepted: list[str] = []


@app.post("/api/projects/{pid}/approve/scenarios")
def approve_scenarios(pid: str, body: Approve):
    p = _p(pid)
    if p.step(2)["status"] not in ("awaiting", "done"):
        raise HTTPException(409, "run the Claude review first")
    p.reset_after(2)
    try:
        job = JOBS.start(pid, "2 approve scenarios", lambda j: steps.approve_scenarios(j, p, body.accepted),
                         lambda j: p.set_step(2, "done", j.result, awaiting=None), lambda j: p.set_step(2, "failed", j.error))
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"job": job.id}


@app.post("/api/projects/{pid}/approve/propagation")
def approve_propagation(pid: str):
    p = _p(pid)
    if p.step(6)["status"] not in ("awaiting", "failed", "done") or not p.has("propagation.json"):
        raise HTTPException(409, "run step 6 first")
    p.reset_after(6)
    p.set_step(6, "running", "assign-sections + finalize")
    try:
        job = JOBS.start(pid, "6 assign + finalize", lambda j: steps.finalize(j, p),
                         lambda j: p.set_step(6, "done", j.result, awaiting=None), lambda j: p.set_step(6, "failed", j.error))
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"job": job.id}


@app.post("/api/projects/{pid}/scenario-ratios")
def scenario_ratios(pid: str):
    p = _p(pid)

    def fn(job):
        job.bridge("scenario-ratios", "--model", p.ap_name, "--scenarios", str(p.file("scenarios.json")),
                   "--out", str(p.file("scenario_ratios.json")), "--commit")
        return "per-scenario ratios cached"
    try:
        job = JOBS.start(pid, "scenario ratios", fn)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"job": job.id}


@app.get("/api/jobs/current")
def current_job(since: int = 0):
    j = JOBS.current
    return j.as_dict(since) if j else {"status": "idle", "log": [], "log_len": 0}
