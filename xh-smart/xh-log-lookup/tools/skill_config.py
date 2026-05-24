"""Shared utilities for reading/writing the service mapping table in SKILL.md."""

from __future__ import annotations

from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent


def _strip_backticks(value: str) -> str:
    value = value.strip()
    if value.startswith("`") and value.endswith("`"):
        value = value[1:-1]
    return value.strip()


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
    for char in line:
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

    Returns list of {"serviceName": ..., "project": ..., "path": ...}.
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
            in_table = True
            continue

        if in_table and all(set(c.replace(":", "").strip()) <= {"-"} for c in cells):
            continue

        if not in_table:
            continue

        service = _strip_backticks(cells[0])
        project = _strip_backticks(cells[1]) if len(cells) > 1 else ""
        path = _strip_backticks(cells[2]) if len(cells) > 2 else ""

        if service:
            rows.append({"serviceName": service, "project": project, "path": path})

    return rows


def render_mapping_table(rows: list[dict[str, str]]) -> str:
    lines = [
        "| serviceName | 项目名 | 仓库路径 |",
        "|----|----|----|",
    ]
    for row in rows:
        path_cell = f"`{row['path']}`" if row["path"] else ""
        lines.append(f"|`{row['serviceName']}`|`{row['project']}`|{path_cell}|")
    return "\n".join(lines)


def read_project_paths(skill_md: Path | None = None) -> dict[str, Path]:
    """Return deduplicated {project_name: Path} from the mapping table."""
    skill_md = skill_md or SKILL_ROOT / "SKILL.md"
    if not skill_md.exists():
        return {}
    text = skill_md.read_text(encoding="utf-8")
    rows = parse_mapping_table(text)
    result: dict[str, Path] = {}
    for row in rows:
        if row["project"] and row["path"] and row["project"] not in result:
            result[row["project"]] = Path(row["path"])
    return result


def get_project_path(project_name: str, skill_md: Path | None = None) -> Path | None:
    paths = read_project_paths(skill_md)
    return paths.get(project_name)
