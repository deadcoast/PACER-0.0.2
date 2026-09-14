"""Register repository assets and Python interfaces through PACER's applying writer.

Run from the PACER repository root using the plugin's uv environment. Preview is
the default. --apply records the current source map under the active nodule.
The script does not infer acceptance, mutate source, or advance task statuses.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

from pacer_mcp.schema import HEADERS
from pacer_mcp.service import Service

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {
    ".git",
    ".cache",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".pacer",
    "dist",
}


def _task(path: str) -> str:
    if (
        path.endswith(("schema.py", "FORMAT.md"))
        or path in {"README.md", "AGENTS.md"}
        or path.startswith("TEMPLATES/")
    ):
        return "PAC-001"
    if path.endswith(("store.py", "validation.py", "test_store.py")):
        return "PAC-002"
    if path.endswith(("query.py", "service.py")):
        return "PAC-003"
    if path.endswith(("commands.py", "test_guards.py", "test_lifecycle.py", "conftest.py")):
        return "PAC-004"
    if path.endswith(("server.py", "test_mcp.py")):
        return "PAC-005"
    if path.startswith("plugins/") and "/tests/" not in path:
        return "PAC-006"
    return "PAC-007"


def source_assets() -> list[dict]:
    """Map repository files and exported Python interfaces to registration metadata."""
    assets = []
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if (
            not path.is_file()
            or set(relative.parts) & EXCLUDED
            or any(p.endswith(".egg-info") for p in relative.parts)
        ):
            continue
        name = relative.as_posix()
        if name.startswith("archive/nodules/"):
            continue  # Canonical register data, not a new source-code asset.
        task = _task(name)
        values = {
            "AssetType": "FILE",
            "Path": name,
            "Symbol": "",
            "Purpose": "",
            "PACRefs": task,
            "OGMRefs": task.replace("PAC-", "OGM-"),
            "NDLRefs": "NDL-001",
            "Tags": "#core #codex",
            "Exports": "",
            "Imports": "",
        }
        if path.suffix == ".py":
            tree = ast.parse(path.read_text(encoding="utf-8"))
            values["Purpose"] = (
                ast.get_docstring(tree) or f"Python module {path.stem}"
            ).splitlines()[0]
            imports = []
            exported = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    imports.extend(f"{node.module}.{alias.name}" for alias in node.names)
                elif isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    exported.extend(
                        target.id
                        for target in node.targets
                        if isinstance(target, ast.Name) and not target.id.startswith("_")
                    )
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    if not node.target.id.startswith("_"):
                        exported.append(node.target.id)
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ) and not node.name.startswith("_"):
                    exported.append(node.name)
                    kind = "CLASS" if isinstance(node, ast.ClassDef) else "FUNCTION"
                    purpose = (ast.get_docstring(node) or f"{node.name} interface").splitlines()[0]
                    assets.append(
                        values
                        | {
                            "AssetType": kind,
                            "Symbol": node.name,
                            "Purpose": purpose,
                            "Exports": node.name,
                        }
                    )
                    if isinstance(node, ast.ClassDef):
                        for method in node.body:
                            if isinstance(
                                method, (ast.FunctionDef, ast.AsyncFunctionDef)
                            ) and not method.name.startswith("_"):
                                symbol = f"{node.name}.{method.name}"
                                assets.append(
                                    values
                                    | {
                                        "AssetType": "METHOD",
                                        "Symbol": symbol,
                                        "Purpose": (
                                            ast.get_docstring(method) or symbol
                                        ).splitlines()[0],
                                        "Exports": symbol,
                                    }
                                )
            values["Exports"] = ";".join(exported)
            values["Imports"] = ";".join(dict.fromkeys(imports))
            module = name.removeprefix("plugins/pacer/src/").removesuffix(".py").replace("/", ".")
            assets.append(values | {"AssetType": "MODULE", "Symbol": module})
            # MCP-decorated nested functions are exported tool/resource/prompt interfaces.
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                    isinstance(d, ast.Call)
                    and isinstance(d.func, ast.Attribute)
                    and d.func.attr in {"tool", "resource", "prompt"}
                    for d in node.decorator_list
                ):
                    assets.append(
                        values
                        | {
                            "AssetType": "FUNCTION",
                            "Symbol": node.name,
                            "Purpose": (
                                ast.get_docstring(node) or f"MCP interface {node.name}"
                            ).splitlines()[0],
                            "Exports": node.name,
                        }
                    )
        elif path.suffix == ".md":
            values["Purpose"] = next(
                (
                    line.lstrip("# ")
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.startswith("# ")
                ),
                "Agent workflow instructions",
            )
        elif name.endswith(".PACER.csv"):
            values["Purpose"] = (
                "PACER worked format example"
                if name.startswith("TEMPLATES/")
                else "Canonical PACER register"
            )
        else:
            values["Purpose"] = f"PACER {path.name} configuration or validation artifact"
        assets.append(values)
    return assets


def main() -> None:
    """Preview or apply source index updates with revision and onboarding guards."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    service = Service(ROOT)
    receipt = service.onboard()
    existing = []
    offset = 0
    while True:
        page = service.query("overlord", fields=HEADERS["overlord"], limit=100, offset=offset)
        existing.extend(page["rows"])
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]
    by_key = {(r["Path"], r["AssetType"], r["Symbol"]): r for r in existing}
    next_id = max([0] + [int(r["ID"].split("-")[1]) for r in existing]) + 1
    operations = []
    assets = source_assets()
    for row in assets:
        key = (row["Path"], row["AssetType"], row["Symbol"])
        old = by_key.get(key)
        if old:
            row["ID"] = old["ID"]
            for field in ("PACRefs", "OGMRefs", "NDLRefs"):
                row[field] = ";".join(
                    dict.fromkeys(
                        v for v in (old.get(field, "") + ";" + row[field]).split(";") if v
                    )
                )
            row["Tags"] = " ".join(dict.fromkeys((old.get("Tags", "") + " " + row["Tags"]).split()))
        else:
            row["ID"] = f"OVR-{next_id:03d}"
            next_id += 1
        by_key[key] = row
    file_map = {r["Path"]: r for r in assets if r["AssetType"] == "FILE"}
    symbol_map = {}
    for row in assets:
        if row["Path"].endswith(".py"):
            module = (
                row["Path"].removeprefix("plugins/pacer/src/").removesuffix(".py").replace("/", ".")
            )
            symbol_map[module + ("." + row["Symbol"] if row["Symbol"] else "")] = row["ID"]
            if module.startswith("scripts."):
                symbol_map[
                    module.removeprefix("scripts.") + ("." + row["Symbol"] if row["Symbol"] else "")
                ] = row["ID"]
    for row in assets:
        requires = []
        if row["AssetType"] != "FILE":
            requires.append(file_map[row["Path"]]["ID"])
        else:
            for imported in row["Imports"].split(";"):
                target = symbol_map.get(imported) or symbol_map.get(imported.rpartition(".")[0])
                if target and target != row["ID"]:
                    requires.append(target)
        row["Requires"] = ";".join(dict.fromkeys(requires))
        old = next((r for r in existing if r["ID"] == row["ID"]), None)
        if old:
            changes = {k: v for k, v in row.items() if k != "ID" and old.get(k, "") != v}
            if changes:
                operations.append({"op": "set", "id": row["ID"], "fields": changes})
        else:
            operations.append({"op": "add", "register": "overlord", "row": row})
    nodule = service.query("nodule", where={"ID": "NDL-001"}, fields=["Status", "NewAssets"])[
        "rows"
    ][0]
    if nodule["Status"] != "ACTIVE":
        raise ValueError("Source indexing changes require an active development nodule")
    new_assets = set(nodule["NewAssets"].split(";")) - {""}
    new_assets.update(
        r["Path"]
        for r in assets
        if r["AssetType"] == "FILE"
        and r["Path"]
        not in {
            "README.md",
            "AGENTS.md",
            *[f"TEMPLATES/{n}.PACER.csv" for n in HEADERS],
            *[f"{n}.PACER.csv" for n in HEADERS],
        }
    )
    operations.append(
        {
            "op": "set",
            "id": "NDL-001",
            "fields": {"NewAssets": ";".join(sorted(new_assets))},
        }
    )
    result = service.apply(
        operations,
        actor="codex",
        revision=receipt["revision"],
        onboarding=receipt["onboarding"],
        preview=not args.apply,
    )
    import json

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
