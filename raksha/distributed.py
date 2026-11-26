"""Offline hospital-worker orchestration and the protected linkage boundary."""

from collections import defaultdict
import hashlib
import hmac
from multiprocessing import get_context
from pathlib import Path
import re


_HOSPITALS = {
    "arogya": "arogya",
    "dhh": "hardoi",
    "dhhardoi": "hardoi",
    "hardoi": "hardoi",
    "jeevanjyoti": "jeevanjyoti",
    "sanjeevani": "sanjeevani",
}


def partition(relative: Path) -> str:
    for part in relative.parts:
        prefix = re.split(r"[^a-z]", part.casefold(), maxsplit=1)[0]
        if prefix in _HOSPITALS:
            return _HOSPITALS[prefix]
    return "unassigned"


def linkage_token(secret: bytes, namespace: str, key: str) -> str:
    token_key = hmac.digest(secret, b"raksha/linkage", "sha256")
    return hmac.new(token_key, f"{namespace}|{key}".encode(), hashlib.sha256).hexdigest()


def coordinate(jobs, worker, resolve, plan_release):
    """Exchange only protected evidence and sanitised release data with workers."""
    context = get_context("spawn")
    active = []
    try:
        for namespace, paths in sorted(jobs.items()):
            parent, child = context.Pipe()
            process = context.Process(target=worker, args=(child, namespace, paths))
            process.start()
            child.close()
            active.append((process, parent, namespace))

        batches = []
        for _, connection, namespace in active:
            kind, evidence = connection.recv()
            if kind != "evidence":
                raise RuntimeError("worker_ingestion_failed")
            batches.append((namespace, evidence))

        decisions = resolve(batches)
        for _, connection, namespace in active:
            connection.send(decisions.get(namespace, {}))

        candidates = []
        for _, connection, _ in active:
            kind, proposed = connection.recv()
            if kind != "candidates":
                raise RuntimeError("worker_plan_failed")
            candidates.extend(proposed)
        revisions = plan_release(candidates)
        for _, connection, namespace in active:
            patients = {patient for patient, _ in decisions.get(namespace, {}).values()}
            connection.send(revisions & patients)

        for _, connection, _ in active:
            kind, payload = connection.recv()
            if kind != "release":
                raise RuntimeError("worker_release_failed")
            yield payload
    finally:
        for process, connection, _ in active:
            connection.close()
            process.join(timeout=2)
            if process.is_alive():
                process.terminate()
                process.join()


def identity_groups(batches):
    """Use scoped matches and unique cross-partition matches for qualified IDs."""
    scopes = defaultdict(set)
    shared_by_local = defaultdict(set)
    claims = defaultdict(lambda: defaultdict(set))
    for namespace, evidence in batches:
        if namespace != "unassigned":
            for local, qualified, shared in evidence:
                scopes[qualified].add(local)
                if shared:
                    shared_by_local[local].add(shared)
                    claims[shared][namespace].add(local)

    merged = {}
    for shared, by_hospital in claims.items():
        if len(by_hospital) < 2 or any(len(ids) != 1 for ids in by_hospital.values()):
            continue
        members = {next(iter(ids)) for ids in by_hospital.values()}
        if all(len(shared_by_local[local]) == 1 for local in members):
            merged.update((local, shared) for local in members)

    for namespace, evidence in batches:
        for local, qualified, _ in sorted(evidence):
            if namespace != "unassigned":
                yield namespace, local, merged.get(local, local)
            elif len(scopes[qualified]) == 1:
                match = next(iter(scopes[qualified]))
                yield namespace, local, merged.get(match, match)
