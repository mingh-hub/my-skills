#!/usr/bin/env python3
"""Resolve per-project repository paths in the SKILL.md mapping table.

Usage:
    python resolve_workspace.py              # auto-detect missing paths and update
    python resolve_workspace.py --check      # check only, no changes
    python resolve_workspace.py --set-project order /path/to/order
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from skill_config import (
    SKILL_ROOT,
    parse_mapping_table,
    render_mapping_table,
)

SKILL_MD = SKILL_ROOT / "SKILL.md"

SEARCH_BASES = [
    Path.home() / "Documents" / "workspace",
    Path.home() / "workspace",
    Path.home() / "projects",
    Path.home() / "dev",
    Path.home() / "code",
]


def _infer_search_dirs(rows: list[dict[str, str]]) -> list[Path]:
    """Derive extra search directories from existing valid paths in the table."""
    parents: set[Path] = set()
    for row in rows:
        if row["path"]:
            p = Path(row["path"])
            if p.is_dir() and p.parent not in parents:
                parents.add(p.parent)
    return list(parents)


def find_project(project_name: str, extra_dirs: list[Path]) -> Path | None:
    for base in extra_dirs:
        candidate = base / project_name
        if candidate.is_dir():
            return candidate

    for base in SEARCH_BASES:
        candidate = base / project_name
        if candidate.is_dir():
            return candidate

    try:
        result = subprocess.run(
            ["mdfind", f"kMDItemFSName == '{project_name}' && kMDItemContentType == 'public.folder'"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.strip().splitlines():
            p = Path(line)
            if p.name == project_name and (p / ".git").is_dir():
                return p
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return None


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
    SKILL_MD.write_text(new_text, encoding="utf-8")


def cmd_resolve(rows: list[dict[str, str]], dry_run: bool) -> int:
    projects = unique_projects(rows)
    extra_dirs = _infer_search_dirs(rows)
    updated = 0
    missing = 0

    for proj, current_path in projects.items():
        if current_path and Path(current_path).is_dir():
            print(f"  OK  {proj} -> {current_path}")
            continue

        found = find_project(proj, extra_dirs)
        if found:
            new_path = str(found)
            print(f"  FIX {proj} -> {new_path}" + (" (dry run)" if dry_run else ""))
            if not dry_run:
                for row in rows:
                    if row["project"] == proj:
                        row["path"] = new_path
            updated += 1
        else:
            print(f"  ???  {proj} -> not found")
            missing += 1

    if updated and not dry_run:
        update_skill_md(rows)
        print(f"\nUpdated {updated} project paths in SKILL.md")

    if missing:
        print(f"\n{missing} project(s) could not be auto-detected")
        return 1
    return 0


def cmd_set_project(rows: list[dict[str, str]], project: str, path: str) -> int:
    resolved = str(Path(path).expanduser().resolve())
    if not Path(resolved).is_dir():
        print(f"ERROR: '{resolved}' is not a directory")
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
