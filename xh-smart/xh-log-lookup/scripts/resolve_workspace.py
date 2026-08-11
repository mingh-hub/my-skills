#!/usr/bin/env python3
"""Resolve per-project repository paths in the SKILL.md mapping table.

Usage:
    python resolve_workspace.py              # auto-detect missing paths and update
    python resolve_workspace.py --check      # check only, no changes
    python resolve_workspace.py --set-project order /path/to/order
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from skill_config import (
    SKILL_ROOT,
    is_trusted_repo,
    parse_mapping_table,
    render_mapping_table,
)

SKILL_MD = SKILL_ROOT / "SKILL.md"


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        resolved = str(path.expanduser())
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(path.expanduser())
    return result


def _split_env_paths(value: str | None) -> list[Path]:
    if not value:
        return []
    return [Path(part).expanduser() for part in value.split(os.pathsep) if part.strip()]


def _infer_search_dirs(rows: list[dict[str, str]]) -> list[Path]:
    """Derive extra search directories from existing valid paths in the table."""
    parents: set[Path] = set()
    for row in rows:
        if row["path"]:
            p = Path(row["path"])
            if p.is_dir() and p.parent not in parents:
                parents.add(p.parent)
    return list(parents)


def _is_trusted_repo(path: Path) -> bool:
    return is_trusted_repo(path)


def _find_candidates(project_name: str, roots: list[Path]) -> list[Path]:
    candidates: list[Path] = []
    for base in roots:
        for candidate in (base / project_name, base / "workspace" / project_name):
            if _is_trusted_repo(candidate):
                candidates.append(candidate)
    return _dedupe_paths(candidates)


def build_search_roots(rows: list[dict[str, str]]) -> list[Path]:
    roots = _split_env_paths(os.environ.get("XH_WORKSPACE_ROOTS"))
    roots.extend(_infer_search_dirs(rows))
    return _dedupe_paths(roots)


def find_project(project_name: str, roots: list[Path]) -> tuple[Path | None, list[Path]]:
    candidates = _find_candidates(project_name, roots)

    if len(candidates) == 1:
        return candidates[0], candidates
    return None, candidates


def unique_projects(rows: list[dict[str, str]]) -> dict[str, str]:
    """Return deduplicated {project_name: current_path}."""
    result: dict[str, str] = {}
    for row in rows:
        proj = row["project"]
        if proj and proj not in result:
            result[proj] = row["path"]
    return result


def update_skill_md(rows: list[dict[str, str]]) -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    table_start = None
    table_end = None
    in_table = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("|"):
            if in_table:
                table_end = i
                break
            continue
        if "serviceName" in stripped:
            table_start = i
            in_table = True
            continue
        if in_table and not stripped.startswith("|"):
            table_end = i
            break

    if table_end is None and in_table:
        table_end = len(lines)

    if table_start is None:
        print("ERROR: mapping table not found in SKILL.md")
        sys.exit(1)

    new_table = render_mapping_table(rows) + "\n"
    new_text = "".join(lines[:table_start]) + new_table + "".join(lines[table_end:])
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=SKILL_MD.parent,
            prefix=f".{SKILL_MD.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_file.write(new_text)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = Path(temp_file.name)
        os.replace(temp_path, SKILL_MD)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def cmd_resolve(rows: list[dict[str, str]], dry_run: bool) -> int:
    projects = unique_projects(rows)
    search_roots = build_search_roots(rows)
    updated = 0
    missing = 0
    conflicts = 0

    for proj, current_path in projects.items():
        if current_path and _is_trusted_repo(Path(current_path)):
            print(f"  OK  {proj} -> {current_path}")
            continue

        found, candidates = find_project(proj, search_roots)
        if found:
            new_path = str(found)
            print(f"  FIX {proj} -> {new_path}" + (" (dry run)" if dry_run else ""))
            if not dry_run:
                for row in rows:
                    if row["project"] == proj:
                        row["path"] = new_path
            updated += 1
        elif candidates:
            print(f"  !!! {proj} -> multiple candidates, choose one with --set-project {proj} <path>")
            for candidate in candidates:
                print(f"      - {candidate}")
            conflicts += 1
        else:
            print(f"  ???  {proj} -> not found")
            missing += 1

    if updated and not dry_run:
        update_skill_md(rows)
        print(f"\nUpdated {updated} project paths in SKILL.md")

    if conflicts:
        print(f"\n{conflicts} project(s) have multiple trusted candidates")
    if missing:
        print(f"{missing} project(s) could not be auto-detected")
    if conflicts or missing:
        return 1
    return 0


def cmd_set_project(rows: list[dict[str, str]], project: str, path: str) -> int:
    resolved = str(Path(path).expanduser().resolve())
    if not _is_trusted_repo(Path(resolved)):
        print(f"ERROR: '{resolved}' is not a trusted source repository")
        return 1

    found = False
    for row in rows:
        if row["project"] == project:
            row["path"] = resolved
            found = True

    if not found:
        print(f"ERROR: project '{project}' not found in mapping table")
        return 1

    update_skill_md(rows)
    print(f"Set {project} -> {resolved}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="Check only, do not modify files")
    parser.add_argument("--set-project", nargs=2, metavar=("PROJECT", "PATH"),
                        help="Set path for a specific project")
    args = parser.parse_args()

    if not SKILL_MD.exists():
        print(f"ERROR: {SKILL_MD} not found")
        return 1

    text = SKILL_MD.read_text(encoding="utf-8")
    rows = parse_mapping_table(text)
    if not rows:
        print("ERROR: no rows found in mapping table")
        return 1

    print(f"Projects: {len(unique_projects(rows))}\n")

    if args.set_project:
        return cmd_set_project(rows, args.set_project[0], args.set_project[1])
    return cmd_resolve(rows, dry_run=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
