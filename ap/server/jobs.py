"""One job at a time, with a live log the browser polls.

A job runs a step function in a thread. Commands go through `Job.run`, which streams their
output into the log and raises StepError on a non-zero exit (allowed codes aside), so the step
stops at the first failure and the browser shows the command's last lines.
"""
from __future__ import annotations

import subprocess
import threading
import time
import traceback
from pathlib import Path
from typing import Callable

AP = Path(__file__).resolve().parents[1]
REPO = AP.parent
BRIDGE = REPO / "tools" / "Quikcolaps.Bridge"
CLI = REPO / "tools" / "Quikcolaps.Cli"


class StepError(RuntimeError):
    pass


class Job:
    def __init__(self, jid: int, project: str, step: str, fn: Callable[["Job"], str | None]):
        self.id, self.project, self.step, self.fn = jid, project, step, fn
        self.status, self.error, self.result = "running", "", ""
        self.log: list[str] = []
        self.started, self.ended = time.time(), None

    def say(self, line: str) -> None:
        self.log.append(line.rstrip())

    def run(self, argv: list[str], cwd: Path = REPO, ok=(0,), label: str | None = None) -> str:
        self.say(f"$ {label or ' '.join(argv)}")
        p = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace", bufsize=1)
        out = []
        for line in p.stdout:
            out.append(line)
            self.say("  " + line.rstrip()[:400])
        code = p.wait()
        if code not in ok:
            tail = [l.strip() for l in out if l.strip()][-3:]
            raise StepError(f"{label or argv[0]} exited {code}" + (": " + " | ".join(tail) if tail else ""))
        return "".join(out)

    def bridge(self, *args: str, ok=(0,)) -> str:
        return self.run(["dotnet", "run", "--no-build", "--project", str(BRIDGE), "--", *args], ok=ok,
                        label="bridge " + " ".join(f'"{a}"' if " " in a else a for a in args))

    def cli(self, *args: str, ok=(0,)) -> str:
        return self.run(["dotnet", "run", "--no-build", "--project", str(CLI), "--", *args], ok=ok,
                        label="quikcolaps " + " ".join(f'"{a}"' if " " in a else a for a in args))

    def py(self, *args: str, ok=(0,)) -> str:
        import sys
        return self.run([sys.executable, *args], cwd=AP, ok=ok, label="python " + " ".join(args))

    def as_dict(self, since: int = 0) -> dict:
        return {"id": self.id, "project": self.project, "step": self.step, "status": self.status,
                "error": self.error, "result": self.result, "log": self.log[since:], "log_len": len(self.log),
                "seconds": round((self.ended or time.time()) - self.started)}


class Jobs:
    def __init__(self):
        self.lock = threading.Lock()
        self.jobs: dict[int, Job] = {}
        self.current: Job | None = None
        self.n = 0

    def start(self, project: str, step: str, fn, on_done=None, on_fail=None) -> Job:
        with self.lock:
            if self.current and self.current.status == "running":
                raise RuntimeError(f"a step is already running ({self.current.step}); wait for it to finish")
            self.n += 1
            job = Job(self.n, project, step, fn)
            self.jobs[job.id] = job
            self.current = job

        def work():
            try:
                job.result = fn(job) or ""
                job.status = "done"
                if on_done:
                    on_done(job)
            except Exception as e:  # noqa: BLE001 - every failure is shown to the user
                job.status = "failed"
                job.error = str(e) if isinstance(e, StepError) else f"{type(e).__name__}: {e}"
                if not isinstance(e, StepError):
                    job.say(traceback.format_exc())
                job.say(f"FAILED: {job.error}")
                if on_fail:
                    on_fail(job)
            finally:
                job.ended = time.time()

        threading.Thread(target=work, daemon=True).start()
        return job


JOBS = Jobs()


def build_tools(job: Job) -> str:
    """dotnet build of the bridge and the Cli tool once, so steps can use --no-build."""
    job.run(["dotnet", "build", str(BRIDGE), "-v", "q", "-nologo"], label="dotnet build bridge")
    job.run(["dotnet", "build", str(CLI), "-v", "q", "-nologo"], label="dotnet build quikcolaps")
    return "built"
