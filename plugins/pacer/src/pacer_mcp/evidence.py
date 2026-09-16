"""Evaluate explicit rules and bind acceptance to current source and meaning."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from pacer_mcp.schema import HEADERS, contained_path, refs
from pacer_mcp.semantics import fingerprint, meaning, rule_errors

ASSET_BASIS = ("Path", "AssetType", "Symbol", "Exports", "Imports", "Requires", "Tags")


def source_digest(root: Path, path: str) -> str | None:
    """Read exact source bytes, returning missing explicitly instead of accepting it."""
    file = contained_path(root, path)
    if not file.is_file():
        return None
    with file.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def register_path(path: str) -> bool:
    """Identify canonical state, which must not recursively hash its own acceptance."""
    return path in {f"{name}.PACER.csv" for name in HEADERS} or path.startswith("archive/nodules/")


def source_basis(row: dict, index: dict, root: Path) -> dict:
    """Follow declared source dependencies and collect stable asset and file fingerprints."""
    pending = refs(row.get("OVRRefs", ""))
    if row.get("RuleSubject"):
        pending.append(row["RuleSubject"])
    assets, sources = {}, {}
    while pending:
        row_id = pending.pop()
        if row_id in assets:
            continue
        asset = index.get(row_id)
        if asset is None or not row_id.startswith("OVR-"):
            raise ValueError(f"REFUSAL: Unknown ID {row_id}")
        assets[row_id] = fingerprint({f: asset.get(f, "") for f in ASSET_BASIS})
        path = asset["Path"]
        if not register_path(path):
            sources[path] = source_digest(root, path)
        pending.extend(refs(asset.get("Requires", "")))
    dependencies = {}
    pending = refs(row.get("BlockedByOGM", ""))
    while pending:
        target = pending.pop()
        if target in dependencies:
            continue
        required = index[target]
        dependencies[target] = fingerprint(
            {
                "meaning": meaning(required),
                "status": required["Status"],
                "evidence": required.get("EvidenceBindings", ""),
            }
        )
        pending.extend(refs(required.get("BlockedByOGM", "")))
    return {
        "version": "0.3",
        "meaning": fingerprint(meaning(row)),
        "assets": assets,
        "sources": sources,
        "dependencies": dependencies,
    }


def json_pointer(value: object, pointer: str) -> object:
    """Resolve RFC 6901 tokens without evaluating code or coercing missing values."""
    if pointer == "":
        return value
    for raw in pointer.split("/")[1:]:
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            # RFC 6901 array indexes use ASCII digits; object keys stay literal.
            if not key.isascii() or not key.isdecimal() or (key != "0" and key.startswith("0")):
                raise KeyError(key)
            value = value[int(key)]
        elif isinstance(value, dict):
            value = value[key]
        else:
            raise KeyError(key)
    return value


def evaluate_rule(row: dict, index: dict, root: Path, artifact: str = "") -> dict:
    """Return observed rule outcome separately from accepted-evidence freshness."""
    return _evaluate_rule(row, index, root, artifact, {}, set())


def _evaluate_rule(
    row: dict, index: dict, root: Path, artifact: str, memo: dict, visiting: set
) -> dict:
    if row["ID"] in memo:
        return memo[row["ID"]]
    if row["ID"] in visiting:
        raise ValueError("REFUSAL: Circular dependency detected")
    visiting.add(row["ID"])
    basis = source_basis(row, index, root)
    result, observed, reason = "UNRESOLVED", None, ""
    kind = row.get("RuleType", "")
    errors = rule_errors(row, index)
    selected_artifact = artifact or row.get("EvidenceArtifact", "")
    if errors or row.get("Authority") in {"", "UNRESOLVED", "LEGACY"} or not kind:
        reason = "; ".join(errors) or "explicit authority and rule required"
    elif any(value is None for value in basis["sources"].values()):
        result, reason = "FAIL", "required source missing"
    elif kind == "manual":
        if selected_artifact:
            asset = index.get(selected_artifact, {})
            if not selected_artifact.startswith("OVR-") or asset.get("AssetType") != "FILE":
                raise ValueError("Manual evidence artifact must resolve to a FILE OVR")
            path = asset["Path"]
            if register_path(path) or path in basis["sources"]:
                raise ValueError("Evidence artifact must be separate from its source basis")
            try:
                report_bytes = contained_path(root, path).read_bytes()
                report = json.loads(report_bytes)
                passed = (
                    report.get("requirement") == row["ID"]
                    and report.get("meaning") == basis["meaning"]
                    and report.get("sources") == basis["sources"]
                    and report.get("result") == "PASS"
                    and isinstance(report.get("command"), list)
                    and bool(report["command"])
                    and all(isinstance(v, str) and v for v in report["command"])
                )
                result = "PASS" if passed else "FAIL"
                reason = "external report assertion; execution honesty requires review"
            except (OSError, ValueError, AttributeError):
                result, reason = "FAIL", "unreadable or invalid manual evidence report"
                report_bytes = b""
            basis["artifact"] = {
                "id": selected_artifact,
                "path": path,
                "sha256": hashlib.sha256(report_bytes).hexdigest(),
            }
        else:
            reason = "manual rule requires a registered source-bound evidence report"
    else:
        subject = index[row["RuleSubject"]]
        try:
            expected = json.loads(row["RuleValue"])
            if kind == "row_eq":
                observed = subject[row["RuleSelector"]]
            elif register_path(subject["Path"]):
                raise ValueError(
                    "Canonical state is evaluated by row rules, not self-hashing files"
                )
            elif kind == "file_sha256":
                observed = source_digest(root, subject["Path"])
            else:
                document_bytes = contained_path(root, subject["Path"]).read_bytes()
                if hashlib.sha256(document_bytes).hexdigest() != basis["sources"][subject["Path"]]:
                    raise ValueError("Source changed during evaluation; evaluate again")
                document = json.loads(document_bytes)
                observed = json_pointer(document, row["RuleSelector"])
            if kind in {"json_ge", "json_le"}:
                numeric = type(observed) is int or (
                    type(observed) is float and math.isfinite(observed)
                )
                passed = numeric and (
                    observed >= expected if kind == "json_ge" else observed <= expected
                )
            else:
                passed = fingerprint(observed) == fingerprint(expected)
            result = "PASS" if passed else "FAIL"
        except (OSError, ValueError, KeyError, IndexError, TypeError, OverflowError) as exc:
            result, reason = "FAIL", str(exc)
    stored = row.get("EvidenceBindings", "")
    freshness = "UNBOUND"
    if stored:
        try:
            accepted = json.loads(stored)
            freshness = "CURRENT" if accepted == basis and result == "PASS" else "STALE"
        except ValueError:
            freshness = "STALE"
    dependencies = {}
    for target in refs(row.get("BlockedByOGM", "")):
        dependency = _evaluate_rule(index[target], index, root, "", memo, visiting)
        dependencies[target] = dependency["freshness"]
        if stored and (
            index[target]["Status"] != "VALIDATED_COMPLETE" or dependency["freshness"] != "CURRENT"
        ):
            freshness = "STALE"
    if source_basis(row, index, root) != {k: v for k, v in basis.items() if k != "artifact"}:
        result, reason = "UNRESOLVED", "Source changed during evaluation; evaluate again"
        freshness = "STALE" if stored else "UNBOUND"
    observation = {
        "id": row["ID"],
        "rule": kind,
        "authority": row.get("Authority", ""),
        "result": result,
        "observed": observed,
        "reason": reason,
        "freshness": freshness,
        "dependencies": dependencies,
        "meaning": basis["meaning"],
        "sources": basis["sources"],
        "basis": basis,
    }
    visiting.remove(row["ID"])
    memo[row["ID"]] = observation
    return observation


def stale_requirements(tables: dict, root: Path) -> list[str]:
    """Find stale accepted claims and propagate invalidity through requirement dependencies."""
    index = {r["ID"]: r for rows in tables.values() for r in rows}
    stale = {
        r["ID"]
        for r in tables["organism"]
        if r["Status"] == "VALIDATED_COMPLETE"
        and r.get("EvidenceBindings")
        and evaluate_rule(r, index, root)["freshness"] != "CURRENT"
    }
    changed = True
    while changed:
        previous = set(stale)
        stale.update(
            r["ID"]
            for r in tables["organism"]
            if r["Status"] == "VALIDATED_COMPLETE" and set(refs(r.get("BlockedByOGM", ""))) & stale
        )
        changed = previous != stale
    return sorted(stale)
