#!/usr/bin/env python3
"""Read-only inspection for source repositories mapped by xh-log-lookup."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


sys.dont_write_bytecode = True
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from skill_config import read_project_paths


MAX_CONTEXT_LINES = 20
MAX_RESULTS = 200
MAX_READ_LINES = 400
MAX_SOURCE_BYTES = 1_000_000
SOURCE_SUFFIXES = {
    ".java",
    ".kt",
    ".kts",
    ".groovy",
    ".gradle",
    ".json",
    ".xml",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".conf",
    ".cfg",
    ".properties",
    ".sql",
    ".proto",
    ".py",
    ".js",
    ".ts",
    ".tsx",
}
SKIP_DIRECTORIES = {
    ".git",
    ".idea",
    ".gradle",
    "build",
    "dist",
    "node_modules",
    "target",
}


class SourceInspectError(ValueError):
    pass


def _resolve_project(project: str, project_paths=None) -> Path:
    paths = project_paths if project_paths is not None else read_project_paths()
    if project not in paths:
        raise SourceInspectError(f"project '{project}' is not mapped in SKILL.md")

    root = Path(paths[project]).expanduser().resolve()
    if not root.is_dir():
        raise SourceInspectError(
            f"project '{project}' path does not exist: {root}; "
            "run resolve_workspace.py --check"
        )
    return root


def _run_git(root: Path, *args: str) -> str:
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    command = [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-C",
        str(root),
        *args,
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            env=env,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired as exc:
        raise SourceInspectError("git command timed out after 10 seconds") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise SourceInspectError(detail)
    return result.stdout.rstrip("\n")


def inspect_status(project: str, project_paths=None) -> dict:
    root = _resolve_project(project, project_paths)
    branch = _run_git(root, "branch", "--show-current") or "DETACHED"
    head = _run_git(root, "rev-parse", "HEAD")
    porcelain = _run_git(root, "status", "--porcelain", "--untracked-files=all")
    changed_files = []
    for line in porcelain.splitlines():
        path = line[3:].strip() if len(line) > 3 else line.strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            changed_files.append(path)

    return {
        "project": project,
        "path": str(root),
        "branch": branch,
        "head": head,
        "dirty": bool(changed_files),
        "changed_files": changed_files,
    }


def _iter_source_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        relative = path.relative_to(root)
        if not _is_allowed_source_path(relative):
            continue
        try:
            resolved = path.resolve(strict=True)
            resolved_relative = resolved.relative_to(root)
            if not _is_allowed_source_path(resolved_relative):
                continue
            if resolved.stat().st_size > MAX_SOURCE_BYTES:
                continue
        except (OSError, ValueError):
            continue
        yield resolved, relative


def _is_allowed_source_path(relative: Path) -> bool:
    if relative.suffix.lower() not in SOURCE_SUFFIXES:
        return False
    return not any(
        part.startswith(".") or part in SKIP_DIRECTORIES
        for part in relative.parts
    )


def _context_rows(lines: list[str], start: int, end: int) -> list[dict]:
    return [
        {"line": index + 1, "text": lines[index]}
        for index in range(start, end)
    ]


def _match_from_path(
    root: Path,
    relative_text: str,
    line_number: int,
    pattern: str,
    context: int,
) -> dict | None:
    relative = Path(relative_text)
    if relative.is_absolute() or not _is_allowed_source_path(relative):
        return None
    try:
        resolved = (root / relative).resolve(strict=True)
        normalized = resolved.relative_to(root)
        if not _is_allowed_source_path(normalized):
            return None
        if resolved.stat().st_size > MAX_SOURCE_BYTES:
            return None
        lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, ValueError):
        return None
    index = line_number - 1
    if index < 0 or index >= len(lines) or pattern not in lines[index]:
        return None
    return {
        "file": relative.as_posix(),
        "line": line_number,
        "text": lines[index],
        "before": _context_rows(lines, max(0, index - context), index),
        "after": _context_rows(lines, index + 1, min(len(lines), index + context + 1)),
    }


def _search_source_rg(
    root: Path,
    pattern: str,
    context: int,
    max_results: int,
) -> tuple[list[dict], bool] | None:
    """Use ripgrep when available; None asks the caller to use Python fallback."""
    rg = shutil.which("rg")
    if not rg:
        return None
    command = [
        rg,
        "--json",
        "--fixed-strings",
        "--line-number",
        "--no-heading",
        "--color=never",
        "--no-follow",
        "--sort=path",
        f"--max-filesize={MAX_SOURCE_BYTES}",
        "--max-count",
        str(max_results + 1),
    ]
    for suffix in sorted(SOURCE_SUFFIXES):
        command.append(f"--glob=*{suffix}")
    for directory in sorted(SKIP_DIRECTORIES):
        command.append(f"--glob=!{directory}/**")
        command.append(f"--glob=!**/{directory}/**")
    command.extend(["--", pattern, str(root)])
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode not in (0, 1):
        return None

    matches = []
    try:
        for raw_line in result.stdout.splitlines():
            event = json.loads(raw_line)
            if event.get("type") != "match":
                continue
            data = event.get("data") or {}
            path_text = ((data.get("path") or {}).get("text") or "").strip()
            if not path_text:
                continue
            path = Path(path_text)
            try:
                relative_text = path.resolve().relative_to(root).as_posix()
            except ValueError:
                continue
            match = _match_from_path(
                root,
                relative_text,
                int(data.get("line_number") or 0),
                pattern,
                context,
            )
            if match is not None:
                matches.append(match)
                if len(matches) > max_results:
                    return matches[:max_results], True
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return matches, False


def _search_source_python(
    root: Path,
    pattern: str,
    context: int,
    max_results: int,
) -> tuple[list[dict], bool]:
    matches = []
    for path, relative in _iter_source_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "\x00" in text:
            continue
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if pattern not in line:
                continue
            matches.append(
                {
                    "file": relative.as_posix(),
                    "line": index + 1,
                    "text": line,
                    "before": _context_rows(lines, max(0, index - context), index),
                    "after": _context_rows(
                        lines, index + 1, min(len(lines), index + context + 1)
                    ),
                }
            )
            if len(matches) >= max_results:
                return matches, True
    return matches, False


def search_source(
    project: str,
    pattern: str,
    context: int = 3,
    max_results: int = 50,
    project_paths=None,
) -> dict:
    if not pattern:
        raise SourceInspectError("search pattern must not be empty")
    if context < 0 or context > MAX_CONTEXT_LINES:
        raise SourceInspectError(f"context must be between 0 and {MAX_CONTEXT_LINES}")
    if max_results < 1 or max_results > MAX_RESULTS:
        raise SourceInspectError(f"max_results must be between 1 and {MAX_RESULTS}")

    root = _resolve_project(project, project_paths)
    rg_result = _search_source_rg(root, pattern, context, max_results)
    matches, truncated = (
        rg_result
        if rg_result is not None
        else _search_source_python(root, pattern, context, max_results)
    )

    return {
        "project": project,
        "path": str(root),
        "pattern": pattern,
        "match_count": len(matches),
        "truncated": truncated,
        "matches": matches,
    }


def _resolve_source_file(root: Path, relative_path: str) -> tuple[Path, Path]:
    requested = Path(relative_path)
    if requested.is_absolute():
        raise SourceInspectError("source file must be inside project and use a relative path")

    resolved = (root / requested).resolve()
    try:
        normalized = resolved.relative_to(root)
    except ValueError as exc:
        raise SourceInspectError("source file must be inside project") from exc

    if not _is_allowed_source_path(normalized):
        raise SourceInspectError(
            "source file must be an allowed source or config file within project"
        )
    if not resolved.is_file():
        raise SourceInspectError(f"source file does not exist: {relative_path}")
    if resolved.stat().st_size > MAX_SOURCE_BYTES:
        raise SourceInspectError(f"source file exceeds {MAX_SOURCE_BYTES} bytes")
    return resolved, normalized


def read_source_file(
    project: str,
    relative_path: str,
    start_line: int,
    end_line: int,
    project_paths=None,
) -> dict:
    if start_line < 1 or end_line < start_line:
        raise SourceInspectError("line range must satisfy 1 <= start_line <= end_line")
    if end_line - start_line + 1 > MAX_READ_LINES:
        raise SourceInspectError(f"a single read may return at most {MAX_READ_LINES} lines")

    root = _resolve_project(project, project_paths)
    source_file, normalized = _resolve_source_file(root, relative_path)
    lines = source_file.read_text(encoding="utf-8", errors="replace").splitlines()
    if start_line > len(lines):
        raise SourceInspectError(
            f"start_line {start_line} exceeds file length {len(lines)}"
        )
    selected = _context_rows(lines, start_line - 1, min(end_line, len(lines)))

    return {
        "project": project,
        "path": str(root),
        "file": normalized.as_posix(),
        "start_line": start_line,
        "end_line": selected[-1]["line"] if selected else start_line,
        "lines": selected,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="project name from SKILL.md mapping")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--status", action="store_true", help="show read-only git status")
    action.add_argument("--search", help="literal source text to search")
    action.add_argument("--file", help="relative source file path to read")
    parser.add_argument("--context", type=int, default=3, help="search context lines, max 20")
    parser.add_argument("--max-results", type=int, default=50, help="search result limit, max 200")
    parser.add_argument("--start-line", type=int, default=1)
    parser.add_argument("--end-line", type=int, default=400)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.status:
            result = inspect_status(args.project)
        elif args.search is not None:
            result = search_source(
                args.project,
                args.search,
                context=args.context,
                max_results=args.max_results,
            )
        else:
            result = read_source_file(
                args.project,
                args.file,
                start_line=args.start_line,
                end_line=args.end_line,
            )
    except (OSError, SourceInspectError) as exc:
        print(
            json.dumps(
                {"status": "error", "error": "source_inspect_failed", "message": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
