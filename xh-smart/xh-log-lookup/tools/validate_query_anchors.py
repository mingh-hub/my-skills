#!/usr/bin/env python3
"""Validate log-skill query templates against source-code anchors.

The checker is intentionally advisory: a warning means "do not trust the
recommended query as the main path", not "the skill is invalid".
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from skill_config import SKILL_ROOT, read_project_paths


def _default_source_roots() -> list[Path]:
    return [p for p in read_project_paths().values() if p.exists()]


@dataclass
class AnchorRow:
    skill: Path
    scene: str
    method_entry: str
    keywords: str
    query: str
    note: str


def strip_md(value: str) -> str:
    value = value.strip()
    if value.startswith("`") and value.endswith("`"):
        value = value[1:-1]
    return value.strip()


def split_markdown_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]

    cells: list[str] = []
    buf: list[str] = []
    in_code = False
    escape = False
    for char in line:
        if escape:
            buf.append(char)
            escape = False
            continue
        if char == "\\":
            buf.append(char)
            escape = True
            continue
        if char == "`":
            in_code = not in_code
            buf.append(char)
            continue
        if char == "|" and not in_code:
            cells.append("".join(buf).strip())
            buf = []
        else:
            buf.append(char)
    cells.append("".join(buf).strip())
    return cells


def parse_anchor_rows(skill_path: Path) -> list[AnchorRow]:
    lines = skill_path.read_text(encoding="utf-8").splitlines()
    rows: list[AnchorRow] = []
    current_header: list[str] | None = None

    for line in lines:
        if not line.strip().startswith("|"):
            current_header = None
            continue

        cells = split_markdown_row(line)
        if len(cells) < 5:
            continue

        if "方法入口" in cells and "推荐查询" in cells:
            current_header = cells
            continue

        if current_header is None:
            continue
        if all(set(cell.replace(":", "").strip()) <= {"-"} for cell in cells):
            continue

        index = {name: i for i, name in enumerate(current_header)}
        try:
            rows.append(
                AnchorRow(
                    skill=skill_path,
                    scene=strip_md(cells[index["场景"]]),
                    method_entry=strip_md(cells[index["方法入口"]]),
                    keywords=strip_md(cells[index["日志锚点/关键词"]]),
                    query=strip_md(cells[index["推荐查询"]]),
                    note=strip_md(cells[index["说明"]]) if "说明" in index else "",
                )
            )
        except (IndexError, KeyError):
            continue

    return rows


def build_class_index(source_roots: Iterable[Path]) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    for root in source_roots:
        if not root.exists():
            continue
        for file_path in root.rglob("*.java"):
            index.setdefault(file_path.stem, []).append(file_path)
    return index


def parse_method_entry(method_entry: str) -> tuple[str | None, str | None, str | None]:
    entry = method_entry.strip()
    if not entry or entry in {"-", "—"} or entry.startswith("待代码确认"):
        return None, None, None

    if "#" in entry:
        class_name, method = entry.split("#", 1)
    else:
        class_name, method = entry, None

    simple_class = class_name.split(".")[-1].strip()
    method = method.strip() if method else None
    return class_name.strip(), simple_class, method


def infer_expected_service(method_entry: str) -> str | None:
    entry = method_entry.lower()
    if "h5-loan" in entry or "h5loan" in entry:
        return "h5-loan"
    if ".order." in entry or entry.startswith("com.xhqb.order"):
        return "order"
    if ".account." in entry or entry.startswith("com.xhqb.account"):
        return "account"
    return None


def extract_service_name(query: str) -> str | None:
    match = re.search(r'serviceName:"([^"]+)"', query)
    return match.group(1) if match else None


def extract_message_anchors(query: str) -> list[str]:
    anchors: list[str] = []
    for raw in re.findall(r'message:"([^"]*)"', query):
        without_placeholders = re.sub(r"\{[^}]*\}", "", raw)
        without_placeholders = without_placeholders.replace("[xxx]", "")
        anchor = without_placeholders.strip()
        anchor = anchor.strip(" ,，:：()（）")
        if len(anchor) >= 2:
            anchors.append(anchor)
    return anchors


def choose_identifier(query: str) -> str:
    for name in ("traceId", "orderId", "contractNo", "cid", "value", "值"):
        if name in query:
            return name if name != "值" else "标识符"
    return "标识符"


def suggest_fallback(query: str, method_entry: str) -> str:
    service = extract_service_name(query) or infer_expected_service(method_entry)
    identifier = choose_identifier(query)
    if service:
        return f'serviceName:"{service}" AND message:"{{{identifier}}}"'
    return f'message:"{{{identifier}}}"'


def find_method_file(
    class_index: dict[str, list[Path]], simple_class: str | None, method: str | None
) -> tuple[Path | None, str, str]:
    if not simple_class:
        return None, "skip", "待代码确认或未填写方法入口"

    candidates = class_index.get(simple_class, [])
    if not candidates:
        return None, "warn", f"未找到类 {simple_class}"

    method_pattern = re.compile(rf"\b{re.escape(method)}\s*\(") if method else None
    for candidate in candidates:
        text = candidate.read_text(encoding="utf-8", errors="ignore")
        if method_pattern is None or method_pattern.search(text):
            return candidate, "ok", "方法入口存在"

    return candidates[0], "warn", f"找到类 {simple_class}，但未找到方法 {method}"


def validate_row(row: AnchorRow, class_index: dict[str, list[Path]]) -> dict[str, object]:
    class_name, simple_class, method = parse_method_entry(row.method_entry)
    source_file, method_status, method_detail = find_method_file(class_index, simple_class, method)

    service_name = extract_service_name(row.query)
    expected_service = infer_expected_service(row.method_entry)
    if expected_service and service_name and expected_service != service_name:
        service_status = "warn"
        service_detail = f"serviceName={service_name}，方法入口推断为 {expected_service}"
    elif service_name:
        service_status = "ok"
        service_detail = f"serviceName={service_name}"
    else:
        service_status = "skip"
        service_detail = "推荐查询未限定 serviceName"

    anchors = extract_message_anchors(row.query)
    if source_file is None:
        message_status = "skip" if method_status == "skip" else "warn"
        missing_anchors = anchors
    elif not anchors:
        message_status = "skip"
        missing_anchors = []
    else:
        text = source_file.read_text(encoding="utf-8", errors="ignore")
        missing_anchors = [anchor for anchor in anchors if anchor not in text]
        message_status = "ok" if not missing_anchors else "warn"

    return {
        "skill": str(row.skill),
        "scene": row.scene,
        "method_entry": row.method_entry,
        "source_file": str(source_file) if source_file else "",
        "method_status": method_status,
        "method_detail": method_detail,
        "service_status": service_status,
        "service_detail": service_detail,
        "message_status": message_status,
        "message_anchors": anchors,
        "missing_message_anchors": missing_anchors,
        "suggested_fallback": suggest_fallback(row.query, row.method_entry),
    }


def overall_status(result: dict[str, object]) -> str:
    statuses = [
        str(result["method_status"]),
        str(result["service_status"]),
        str(result["message_status"]),
    ]
    if "warn" in statuses:
        return "WARN"
    if all(status in {"ok", "skip"} for status in statuses):
        return "OK"
    return "INFO"


def print_text(results: list[dict[str, object]]) -> None:
    for result in results:
        status = overall_status(result)
        print(f"[{status}] {Path(str(result['skill'])).parent.name} / {result['scene']}")
        print(f"  method: {result['method_status']} - {result['method_detail']}")
        print(f"  service: {result['service_status']} - {result['service_detail']}")
        if result["message_anchors"]:
            print(f"  message anchors: {', '.join(result['message_anchors'])}")
        else:
            print("  message anchors: (none)")
        if result["missing_message_anchors"]:
            print(f"  missing anchors: {', '.join(result['missing_message_anchors'])}")
        print(f"  fallback: {result['suggested_fallback']}")
        print()


def discover_sub_skills() -> list[Path]:
    skill_root = Path(__file__).resolve().parent.parent
    paths = sorted(skill_root.glob("xh-log-lookup-*/SKILL.md"))
    return paths


def warn_reason(result: dict[str, object]) -> str:
    parts: list[str] = []
    if result["method_status"] == "warn":
        parts.append(str(result["method_detail"]))
    if result["service_status"] == "warn":
        parts.append(str(result["service_detail"]))
    if result["missing_message_anchors"]:
        anchors = ", ".join(result["missing_message_anchors"])
        parts.append(f"锚点未匹配: {anchors}")
    return "; ".join(parts)


def print_summary(results: list[dict[str, object]]) -> None:
    col_mod = max(len(Path(str(r["skill"])).parent.name) for r in results)
    col_mod = max(col_mod, 4)
    col_scene = max(len(str(r["scene"])) for r in results)
    col_scene = max(col_scene, 4)

    header = f"{'模块':<{col_mod}}  {'场景':<{col_scene}}  有效"
    sep = "─" * (col_mod + col_scene + 8)

    print("=== 锚点有效性汇总 ===")
    print(header)
    print(sep)

    ok_count = 0
    warn_count = 0
    for r in results:
        status = overall_status(r)
        mod_name = Path(str(r["skill"])).parent.name
        valid = "Y" if status != "WARN" else "N"
        line = f"{mod_name:<{col_mod}}  {str(r['scene']):<{col_scene}}  {valid}"
        if valid == "N":
            line += f"  ← {warn_reason(r)}"
            warn_count += 1
        else:
            ok_count += 1
        print(line)

    print(sep)
    print(f"合计: {len(results)} 条 | 有效: {ok_count} | 无效: {warn_count}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--skill", action="append", help="Path to a SKILL.md file")
    group.add_argument("--all", action="store_true", help="Auto-discover all sub-skill SKILL.md files")
    parser.add_argument(
        "--source-root",
        action="append",
        type=Path,
        default=[],
        help="Source repository root. Can be provided multiple times.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    parser.add_argument("--summary", action="store_true", help="Print concise summary table")
    args = parser.parse_args()

    if args.all:
        skill_paths = discover_sub_skills()
        if not skill_paths:
            print("未发现任何 xh-log-lookup-*/SKILL.md 子模块")
            return 1
    else:
        skill_paths = [Path(s) for s in args.skill]

    source_roots = args.source_root or [root for root in _default_source_roots() if root.exists()]
    class_index = build_class_index(source_roots)

    rows: list[AnchorRow] = []
    for skill in skill_paths:
        rows.extend(parse_anchor_rows(skill))

    results = [validate_row(row, class_index) for row in rows]
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif args.summary:
        print_summary(results)
    else:
        print_text(results)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
