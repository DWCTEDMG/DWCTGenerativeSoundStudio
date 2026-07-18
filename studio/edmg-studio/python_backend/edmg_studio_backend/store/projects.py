from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PROJECT_ID_RE = re.compile(r"^[0-9a-f]{32}$")

@dataclass
class Project:
    id: str
    name: str
    created_at: str
    meta: dict[str, Any]

class ProjectStore:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.projects_dir = self.base_dir / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def _validate_project_id(self, project_id: str) -> str:
        pid = str(project_id or "").strip()
        if not _PROJECT_ID_RE.fullmatch(pid):
            raise ValueError("Invalid project_id")
        return pid

    def _proj_dir(self, project_id: str) -> Path:
        pid = self._validate_project_id(project_id)
        d = self.projects_dir / pid
        d.mkdir(parents=True, exist_ok=True)
        (d / "assets" / "audio").mkdir(parents=True, exist_ok=True)
        (d / "assets" / "overlays").mkdir(parents=True, exist_ok=True)
        (d / "assets" / "masks").mkdir(parents=True, exist_ok=True)
        (d / "assets" / "fonts").mkdir(parents=True, exist_ok=True)
        (d / "analysis").mkdir(parents=True, exist_ok=True)
        (d / "outputs" / "images").mkdir(parents=True, exist_ok=True)
        (d / "outputs" / "videos").mkdir(parents=True, exist_ok=True)
        (d / "outputs" / "deforum").mkdir(parents=True, exist_ok=True)
        (d / "outputs" / "unreal").mkdir(parents=True, exist_ok=True)
        (d / "jobs").mkdir(parents=True, exist_ok=True)
        return d

    def list(self) -> list[Project]:
        out: list[Project] = []
        for d in sorted(self.projects_dir.iterdir()):
            if not d.is_dir():
                continue
            pj = d / "project.json"
            if not pj.exists():
                continue
            try:
                data = json.loads(pj.read_text(encoding="utf-8"))
                out.append(Project(**data))
            except Exception:
                continue
        return out

    def create(self, name: str) -> Project:
        pid = uuid.uuid4().hex
        created_at = time.strftime("%Y-%m-%d %H:%M:%S")
        proj = Project(id=pid, name=name, created_at=created_at, meta={})
        self.save(proj)
        self._proj_dir(pid)
        return proj

    def get(self, project_id: str) -> Project | None:
        pid = self._validate_project_id(project_id)
        pj = self.projects_dir / pid / "project.json"
        if not pj.exists():
            return None
        data = json.loads(pj.read_text(encoding="utf-8"))
        return Project(**data)

    def save(self, proj: Project) -> None:
        d = self._proj_dir(proj.id)
        target = d / "project.json"
        tmp = d / "project.json.tmp"
        payload = json.dumps({
            "id": proj.id,
            "name": proj.name,
            "created_at": proj.created_at,
            "meta": proj.meta
        }, ensure_ascii=False, indent=2)
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)

    def project_dir(self, project_id: str) -> Path:
        return self._proj_dir(project_id)

    def set_audio(self, project_id: str, filename: str, bytes_len: int) -> None:
        proj = self.get(project_id)
        if not proj:
            raise KeyError("Project not found")
        proj.meta["audio"] = {"filename": filename, "size_bytes": bytes_len}
        self.save(proj)
