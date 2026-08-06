"""Shared utilities for reading/writing the service mapping table in SKILL.md."""

from __future__ import annotations

import os
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
REPO_MARKERS = (".git", "pom.xml", "build.gradle", "settings.gradle", "package.json")


def _strip_backticks(value: str) -> str:
    value = value.strip()
    if value.startswith("`") and value.endswith("`"):
        value = value[1:-1]
    return value.strip()


def _contains_unescaped_pipe(value: str) -> bool:
    escaped = False
    for char in value:
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            return True
    return False


def _validate_markdown_field(field: str, value: str) -> None:
    if "`" in value or "\n" in value or "\r" in value:
        raise ValueError(f"mapping field {field} contains unsupported markdown")
    if _contains_unescaped_pipe(value):
        raise ValueError(f"mapping field {field} contains an unescaped pipe")


def _split_row(line: str) -> list[str]:
    """Split a markdown table row into cells, respecting backtick spans."""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]

    cells: list[str] = []
    buf: list[str] = []
    in_code = False
    escaped = False
    for char in line:
        if escaped:
            buf.append(char)
            escaped = False
            continue
        if char == "\\":
            buf.append(char)
            escaped = True
            continue
        if char == "`":
            in_code = not in_code
            buf.append(char)
        elif char == "|" and not in_code:
            cells.append("".join(buf).strip())
            buf = []
        else:
            buf.append(char)
    cells.append("".join(buf).strip())
    return cells


def parse_mapping_table(text: str) -> list[dict[str, str]]:
    """Parse the service mapping table from SKILL.md text.

    Returns list of {"serviceName": ..., "project": ..., "alias": ..., "path": ...}.
    """
    rows: list[dict[str, str]] = []
    in_table = False

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if in_table:
                break
            continue

        cells = _split_row(stripped)
        if len(cells) < 2:
            continue

        if "serviceName" in cells[0]:
            expected = ["serviceName", "项目名", "别名", "仓库路径"]
            if [_strip_backticks(cell) for cell in cells] != expected:
                raise ValueError(
                    "service mapping table header must be: " + " | ".join(expected)
                )
            in_table = True
            continue

        if in_table and all(set(c.replace(":", "").strip()) <= {"-"} for c in cells):
            continue

        if not in_table:
            continue

        if len(cells) != 4:
            raise ValueError(
                f"service mapping row must contain 4 columns, got {len(cells)}: {stripped}"
            )

        service = _strip_backticks(cells[0])
        project = _strip_backticks(cells[1]) if len(cells) > 1 else ""
        alias = _strip_backticks(cells[2])
        path = _strip_backticks(cells[3])

        if service:
            rows.append({"serviceName": service, "project": project, "alias": alias, "path": path})

    _validate_mapping_rows(rows)
    return rows


def _validate_mapping_rows(rows: list[dict[str, str]]) -> None:
    services: set[str] = set()
    project_paths: dict[str, str] = {}
    for row in rows:
        for field in ("serviceName", "project", "alias", "path"):
            _validate_markdown_field(field, row.get(field, ""))
        service = row["serviceName"]
        project = row["project"]
        path = row["path"]
        if service in services:
            raise ValueError(f"duplicate serviceName in mapping table: {service}")
        services.add(service)
        if not project:
            raise ValueError(f"project is required for serviceName: {service}")
        existing = project_paths.get(project, "")
        if existing and path and Path(existing).expanduser() != Path(path).expanduser():
            raise ValueError(
                f"conflicting paths for project {project}: {existing} != {path}"
            )
        if path:
            project_paths[project] = path


def render_mapping_table(rows: list[dict[str, str]]) -> str:
    _validate_mapping_rows(rows)
    lines = [
        "| serviceName | 项目名 | 别名 | 仓库路径 |",
        "|----|----|----|----|",
    ]
    for row in rows:
        path_cell = f"`{row['path']}`" if row["path"] else ""
        alias = row.get("alias", "")
        alias_cell = f"`{alias}`" if alias else ""
        lines.append(f"|`{row['serviceName']}`|`{row['project']}`|{alias_cell}|{path_cell}|")
    return "\n".join(lines)


def is_trusted_repo(path: Path) -> bool:
    path = path.expanduser()
    return path.is_dir() and any((path / marker).exists() for marker in REPO_MARKERS)


def _workspace_roots() -> list[Path]:
    value = os.environ.get("XH_WORKSPACE_ROOTS", "")
    roots: list[Path] = []
    seen: set[str] = set()
    for raw in value.split(os.pathsep):
        if not raw.strip():
            continue
        root = Path(raw).expanduser()
        key = str(root)
        if key not in seen:
            seen.add(key)
            roots.append(root)
    return roots


def _resolve_from_workspace_roots(project: str) -> Path | None:
    candidates: list[Path] = []
    seen: set[str] = set()
    for root in _workspace_roots():
        for candidate in (root / project, root / "workspace" / project):
            key = str(candidate)
            if key not in seen and is_trusted_repo(candidate):
                seen.add(key)
                candidates.append(candidate)
    return candidates[0] if len(candidates) == 1 else None


def read_project_paths(skill_md: Path | None = None) -> dict[str, Path]:
    """Return deduplicated {project_name: Path} from the mapping table."""
    skill_md = skill_md or SKILL_ROOT / "SKILL.md"
    if not skill_md.exists():
        return {}
    text = skill_md.read_text(encoding="utf-8")
    rows = parse_mapping_table(text)
    result: dict[str, Path] = {}
    for row in rows:
        project = row["project"]
        if not project or project in result:
            continue
        cached = Path(row["path"]).expanduser() if row["path"] else None
        if cached is not None and is_trusted_repo(cached):
            result[project] = cached
            continue
        resolved = _resolve_from_workspace_roots(project)
        if resolved is not None:
            result[project] = resolved
        elif cached is not None:
            # Preserve the old diagnostic path when runtime discovery cannot help.
            result[project] = cached
    return result


def get_project_path(project_name: str, skill_md: Path | None = None) -> Path | None:
    paths = read_project_paths(skill_md)
    return paths.get(project_name)
