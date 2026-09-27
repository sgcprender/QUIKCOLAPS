"""Projects: the index the landing page reads, and each project's state and folder.

Index: ap/projects.json (machine-local, not in git): [{"id", "folder"}]. Each project keeps its
own state in "<folder>/project.json", and all its data files in that folder, which sits next to
the model as "<name> - quikcolaps". The model the user picks is never modified: the app works on
copies in the same folder, "<name> - AP.edb" (collapse) and "<name> - baseline.edb" (strength).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

AP = Path(__file__).resolve().parents[1]
INDEX = AP / "projects.json"

STEPS = [
    (0, "Check model"),
    (1, "Load model"),
    (2, "Claude review"),
    (3, "Write to Engine"),
    (4, "Run + design"),
    (5, "Redesign rounds"),
    (6, "Copy to similar & finalize"),
    (7, "Tonnage & report"),
]


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def pid_for(folder: Path) -> str:
    return hashlib.sha1(str(folder.resolve()).lower().encode()).hexdigest()[:10]


def read_index() -> list[dict]:
    return json.loads(INDEX.read_text()) if INDEX.exists() else []


def write_index(items: list[dict]) -> None:
    INDEX.write_text(json.dumps(items, indent=1))


class Project:
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.path = self.folder / "project.json"
        self.state = json.loads(self.path.read_text())

    @property
    def id(self) -> str:
        return self.state["id"]

    def save(self) -> None:
        self.state["updated"] = now()
        self.path.write_text(json.dumps(self.state, indent=1))

    def file(self, name: str) -> Path:
        return self.folder / name

    def has(self, *names: str) -> bool:
        return all(self.file(n).exists() for n in names)

    def load(self, name: str):
        p = self.file(name)
        return json.loads(p.read_text()) if p.exists() else None

    @property
    def ap_model(self) -> Path:
        return Path(self.state["ap_model"])

    @property
    def baseline_model(self) -> Path:
        return Path(self.state["baseline_model"])

    @property
    def ap_name(self) -> str:
        """The name passed to every bridge command (--model): the working copy's file stem."""
        return self.ap_model.stem

    @property
    def baseline_name(self) -> str:
        return self.baseline_model.stem

    def step(self, n: int) -> dict:
        return self.state["steps"].setdefault(str(n), {"status": "todo"})

    def set_step(self, n: int, status: str, message: str = "", **extra) -> None:
        s = self.step(n)
        s.update({"status": status, "message": message, "at": now(), **extra})
        if status == "done":
            self.state["last_completed"] = max(self.state.get("last_completed", -1), n)
        self.save()

    def reset_after(self, n: int) -> None:
        """A step that runs again makes the later ones out of date: back to todo (files are kept)."""
        for k in range(n + 1, len(STEPS)):
            if self.step(k)["status"] != "todo":
                self.state["steps"][str(k)] = {"status": "todo", "message": "earlier step ran again", "at": now()}
        self.state["last_completed"] = min(self.state.get("last_completed", -1), n - 1)
        self.save()

    def summary(self) -> dict:
        t = self.load("collapse_tonnage.json") or {}
        prem = t.get("premium")
        last = self.state.get("last_completed", -1)
        last_status = self.step(last)["status"] if last >= 0 else "not started"
        fin = self.load("finalize.json") or {}
        return {
            "id": self.id, "name": self.state["name"], "folder": str(self.folder),
            "source_model": self.state["source_model"], "ap_model": self.state["ap_model"],
            "baseline_model": self.state["baseline_model"],
            "created": self.state["created"], "updated": self.state.get("updated", self.state["created"]),
            "last_completed": last, "last_completed_name": STEPS[last][1] if last >= 0 else None,
            "last_status": last_status, "finalize": fin.get("status"),
            "premium": prem, "tonnage": (t.get("tonnage") or {}).get("total"),
            "baseline": t.get("baseline_total"), "demo": self.state.get("demo", False),
        }


def create(model: Path, name: str | None = None) -> tuple[Project, list[str]]:
    """New project for a picked model: folder and working copies (never touching the model)."""
    model = Path(model).resolve()
    if model.suffix.lower() != ".edb":
        raise ValueError(f"{model.name} is not an Engine model (.edb)")
    if not model.exists():
        raise ValueError(f"{model} not found")
    name = name or model.stem
    folder = model.parent / f"{name} - quikcolaps"
    notes = []
    folder.mkdir(exist_ok=True)
    ap_model = model.parent / f"{name} - AP.edb"
    base = model.parent / f"{name} - baseline.edb"
    for copy in (ap_model, base):
        if copy.exists():
            notes.append(f"{copy.name} already exists; kept as it is")
        else:
            shutil.copy2(model, copy)
            notes.append(f"copied {model.name} to {copy.name}")
    if (folder / "project.json").exists():
        p = Project(folder)
        notes.append("project folder already exists; opened it")
    else:
        state = {"id": pid_for(folder), "name": name, "source_model": str(model), "ap_model": str(ap_model),
                 "baseline_model": str(base), "created": now(), "steps": {}, "last_completed": -1,
                 "strength_combos": ["DStlS1", "DStlS2"], "template": "CS1"}
        (folder / "project.json").write_text(json.dumps(state, indent=1))
        p = Project(folder)
    register(p)
    return p, notes


def register(p: Project) -> None:
    items = [x for x in read_index() if x["id"] != p.id]
    write_index([{"id": p.id, "folder": str(p.folder)}] + items)


def remove(pid: str) -> None:
    """Remove from the list only; the folder and models stay on disk."""
    write_index([x for x in read_index() if x["id"] != pid])


def all_projects() -> list[Project]:
    out = []
    for x in read_index():
        f = Path(x["folder"])
        if (f / "project.json").exists():
            out.append(Project(f))
    return out


def get(pid: str) -> Project:
    for p in all_projects():
        if p.id == pid:
            return p
    raise KeyError(pid)
