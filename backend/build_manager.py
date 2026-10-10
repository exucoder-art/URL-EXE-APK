"""
Build job manager – tracks status, rate limits, and coordinates workers.
In production this would use Celery + Redis. Here we provide a robust
in-memory + file-based implementation that works without external services,
plus optional Celery hooks.
"""
from __future__ import annotations

import json
import time
import uuid
import threading
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
from collections import defaultdict

from config import Config


class BuildManager:
    def __init__(self):
        self.jobs: dict[str, dict[str, Any]] = {}
        self.lock = threading.RLock()
        self.ip_history: dict[str, list[float]] = defaultdict(list)
        self._load_persisted()

    def _job_path(self, job_id: str) -> Path:
        return Config.BUILD_FOLDER / f"{job_id}.json"

    def _persist(self, job: dict):
        """Best-effort persistence – never crash the worker on I/O errors."""
        try:
            path = self._job_path(job["id"])
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(job, f, indent=2, default=str)
            tmp.replace(path)
        except OSError:
            # Sandbox or disk issues – keep in-memory only
            pass

    def _load_persisted(self):
        for p in Config.BUILD_FOLDER.glob("*.json"):
            try:
                with open(p, encoding="utf-8") as f:
                    job = json.load(f)
                    if job.get("id"):
                        self.jobs[job["id"]] = job
            except Exception:
                pass

    def _check_rate_limit(self, ip: str) -> tuple[bool, str]:
        now = time.time()
        window = 3600  # 1 hour
        history = self.ip_history[ip]
        # prune
        self.ip_history[ip] = [t for t in history if now - t < window]
        if len(self.ip_history[ip]) >= Config.MAX_BUILDS_PER_IP_PER_HOUR:
            return False, f"Rate limit exceeded. Max {Config.MAX_BUILDS_PER_IP_PER_HOUR} builds per hour."
        return True, ""

    def create_job(
        self,
        url: str,
        app_name: str,
        package_name: str,
        theme_color: str,
        targets: list[str],
        icon_path: str | None,
        ip: str,
        metadata: dict | None = None,
    ) -> tuple[dict | None, str]:
        ok, msg = self._check_rate_limit(ip)
        if not ok:
            return None, msg

        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        job = {
            "id": job_id,
            "url": url,
            "app_name": app_name,
            "package_name": package_name,
            "theme_color": theme_color,
            "targets": targets,  # ["apk", "exe"] or subset
            "icon_path": icon_path,
            "metadata": metadata or {},
            "status": "queued",  # queued | building | completed | failed
            "progress": 0,
            "message": "Queued for build",
            "created_at": now,
            "updated_at": now,
            "ip": hashlib.sha256(ip.encode()).hexdigest()[:16],  # anonymized
            "artifacts": {},  # target -> relative path
            "logs": [],
            "error": None,
        }

        with self.lock:
            self.jobs[job_id] = job
            self.ip_history[ip].append(time.time())
            self._persist(job)

        return job, ""

    def get_job(self, job_id: str) -> dict | None:
        with self.lock:
            return self.jobs.get(job_id)

    def update_job(self, job_id: str, **kwargs):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            job.update(kwargs)
            job["updated_at"] = datetime.now(timezone.utc).isoformat()
            if "logs" in kwargs:
                # already set
                pass
            self._persist(job)

    def append_log(self, job_id: str, line: str):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            job.setdefault("logs", []).append(
                {"ts": datetime.now(timezone.utc).isoformat(), "msg": line}
            )
            # keep last 100 lines
            job["logs"] = job["logs"][-100:]
            job["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._persist(job)

    def list_recent(self, limit: int = 20) -> list[dict]:
        with self.lock:
            jobs = sorted(
                self.jobs.values(),
                key=lambda j: j.get("created_at", ""),
                reverse=True,
            )
            # strip sensitive
            return [
                {
                    "id": j["id"],
                    "app_name": j["app_name"],
                    "status": j["status"],
                    "progress": j["progress"],
                    "targets": j["targets"],
                    "created_at": j["created_at"],
                }
                for j in jobs[:limit]
            ]


# Singleton
build_manager = BuildManager()
