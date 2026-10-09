"""Executor backends (Section 9). The simulated executor is the default; the Kubernetes adapter is a
swappable interface that turns a planned start into a batch/v1 Job manifest.

HONESTY: the Kubernetes backend here renders manifests (dry-run, optionally `kubectl apply`). It was NOT
run against a real cluster in this repo, and completion is still driven by the simulated clock.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Protocol


class ExecutorBackend(Protocol):
    name: str

    def on_start(self, job, ts: str) -> None: ...
    def on_finish(self, job, ts: str) -> None: ...


class SimBackend:
    name = "simulated"

    def on_start(self, job, ts: str) -> None:
        pass

    def on_finish(self, job, ts: str) -> None:
        pass


def k8s_name(job_id: str) -> str:
    n = re.sub(r"[^a-z0-9-]+", "-", job_id.lower()).strip("-")
    return ("cas-" + n)[:63].rstrip("-")


def job_manifest(job, ts: str, image: str = "busybox:1.36", namespace: str = "default") -> dict:
    """batch/v1 Job for a started carbon-aware job. Power is declared via annotation, not enforced."""
    return {
        "apiVersion": "batch/v1", "kind": "Job",
        "metadata": {"name": k8s_name(job.id), "namespace": namespace,
                     "labels": {"app": "carbon-aware-scheduler", "workload-type": job.wtype},
                     "annotations": {"carbon-scheduler/planned-start": ts,
                                     "carbon-scheduler/region": str(job.region),
                                     "carbon-scheduler/declared-power-kw": str(job.kw)}},
        "spec": {"backoffLimit": 0, "ttlSecondsAfterFinished": 3600,
                 "template": {"spec": {"restartPolicy": "Never",
                                       "containers": [{"name": "work", "image": image,
                                                       "command": ["sh", "-c", f"sleep {max(1, job.an * 30 * 60)}"],
                                                       "resources": {"requests": {"cpu": "500m"}}}]}}},
    }


class KubernetesBackend:
    name = "kubernetes"

    def __init__(self, apply: bool = False, namespace: str = "default", image: str = "busybox:1.36"):
        self.apply, self.namespace, self.image = apply, namespace, image
        self.manifests: list[dict] = []

    def on_start(self, job, ts: str) -> None:
        m = job_manifest(job, ts, self.image, self.namespace)
        self.manifests.append(m)
        if self.apply:
            if not shutil.which("kubectl"):
                raise RuntimeError("kubectl not found; run with apply=False for dry-run manifests")
            subprocess.run(["kubectl", "apply", "-f", "-"], input=json.dumps(m), text=True, check=True)

    def on_finish(self, job, ts: str) -> None:
        pass
