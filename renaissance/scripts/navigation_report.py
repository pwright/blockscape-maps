#!/usr/bin/env python3

import argparse
import json
from collections import deque
from pathlib import Path
import re
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parent.parent
FILENAME_AT_END = re.compile(r"([A-Za-z0-9._-]+\.bs)$")


def load_spec(path: Path):
    data = json.loads(path.read_text())
    if isinstance(data, list):
        if not data:
            raise ValueError(f"{path.name} contains an empty array")
        return data[0]
    if isinstance(data, dict):
        return data
    raise ValueError(f"{path.name} does not contain a JSON object or array")


def walk(node, visit):
    if isinstance(node, dict):
        visit(node)
        for value in node.values():
            walk(value, visit)
    elif isinstance(node, list):
        for item in node:
            walk(item, visit)


def extract_target_filename(external: str):
    decoded = unquote(external)
    match = FILENAME_AT_END.search(decoded)
    if match:
        target_name = Path(match.group(1)).name
        return target_name, "suffix"

    parsed = urlparse(external)
    if parsed.scheme in {"http", "https"}:
        query_load = parse_qs(parsed.query).get("load")
        if query_load:
            load_url = unquote(query_load[0])
            load_parsed = urlparse(load_url)
            target_name = Path(load_parsed.path).name
            if target_name.endswith(".bs"):
                return target_name, "blockscape"
        target_name = Path(parsed.path).name
        if target_name.endswith(".bs"):
            return target_name, "direct"
        return None, "external"

    if external.endswith(".bs"):
        return Path(external).name, "relative"

    return None, "external"


def collect_links(path: Path, local_filenames):
    spec = load_spec(path)
    links = []

    def visit(node):
        if not isinstance(node, dict):
            return

        item_id = node.get("id")
        external = node.get("external")
        is_navigable_item = isinstance(node.get("name"), str) or "deps" in node

        if not is_navigable_item:
            return

        target_from_id = f"{item_id}.bs" if isinstance(item_id, str) else None

        if (
            isinstance(item_id, str)
            and item_id != path.stem
            and target_from_id in local_filenames
        ):
            links.append(
                {
                    "source_item_id": item_id,
                    "external": external if isinstance(external, str) else None,
                    "target_filename": target_from_id,
                    "kind": "id-match",
                }
            )
            return

        if not isinstance(external, str):
            return

        target_filename, kind = extract_target_filename(external)
        links.append(
            {
                "source_item_id": item_id,
                "external": external,
                "target_filename": target_filename,
                "kind": kind,
            }
        )

    walk(spec, visit)
    return spec, links


def build_report(start_filename: str):
    bs_files = sorted(ROOT.glob("*.bs"))
    file_map = {path.name: path for path in bs_files}
    if start_filename not in file_map:
        raise FileNotFoundError(f"Start file not found: {start_filename}")

    queue = deque([(start_filename, 0)])
    seen = {start_filename}
    reachable = []
    edges = []
    broken_local_targets = []
    non_local_links = []

    while queue:
        filename, depth = queue.popleft()
        path = file_map[filename]
        spec, links = collect_links(path, set(file_map))
        reachable.append(
            {
                "filename": filename,
                "depth": depth,
                "id": spec.get("id"),
                "title": spec.get("title"),
                "outbound_link_count": len(links),
            }
        )

        for link in links:
            record = {
                "from_file": filename,
                "from_item_id": link["source_item_id"],
                "external": link["external"],
                "kind": link["kind"],
                "target_filename": link["target_filename"],
            }
            edges.append(record)

            target_filename = link["target_filename"]
            if target_filename is None:
                non_local_links.append(record)
                continue

            if target_filename not in file_map:
                broken_local_targets.append(record)
                continue

            if target_filename not in seen:
                seen.add(target_filename)
                queue.append((target_filename, depth + 1))

    unreachable = [
        {"filename": path.name}
        for path in bs_files
        if path.name not in seen
    ]

    return {
        "start_file": start_filename,
        "reachable_count": len(reachable),
        "total_bs_files": len(bs_files),
        "unreachable_count": len(unreachable),
        "reachable_files": sorted(reachable, key=lambda item: (item["depth"], item["filename"])),
        "unreachable_files": unreachable,
        "edges": edges,
        "broken_local_targets": broken_local_targets,
        "non_local_links": non_local_links,
    }


def render_text(report):
    lines = []
    lines.append(f"Start file: {report['start_file']}")
    lines.append(
        "Reachable local specs: "
        f"{report['reachable_count']} / {report['total_bs_files']}"
    )
    lines.append(f"Unreachable local specs: {report['unreachable_count']}")
    lines.append(f"Broken local targets: {len(report['broken_local_targets'])}")
    lines.append(f"Non-local external links: {len(report['non_local_links'])}")
    lines.append("")
    lines.append("Reachable files by depth:")
    for item in report["reachable_files"]:
        title = f" - {item['title']}" if item.get("title") else ""
        lines.append(
            f"  depth {item['depth']}: {item['filename']} "
            f"(id={item.get('id')}, links={item['outbound_link_count']}){title}"
        )

    if report["broken_local_targets"]:
        lines.append("")
        lines.append("Broken local targets:")
        for item in sorted(
            report["broken_local_targets"],
            key=lambda value: (value["from_file"], value["target_filename"] or ""),
        ):
            lines.append(
                f"  {item['from_file']} -> {item['target_filename']} "
                f"(item id={item['from_item_id']}, kind={item['kind']})"
            )

    if report["non_local_links"]:
        lines.append("")
        lines.append("Non-local external links:")
        for item in sorted(
            report["non_local_links"],
            key=lambda value: (value["from_file"], value["external"]),
        ):
            lines.append(
                f"  {item['from_file']} -> {item['external']} "
                f"(item id={item['from_item_id']}, kind={item['kind']})"
            )

    if report["unreachable_files"]:
        lines.append("")
        lines.append("Unreachable local files:")
        for item in report["unreachable_files"]:
            lines.append(f"  {item['filename']}")

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description="Report which .bs specs are discoverable from a starting file."
    )
    parser.add_argument(
        "start",
        nargs="?",
        default="root.bs",
        help="Starting .bs file. Defaults to root.bs.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of plain text.",
    )
    args = parser.parse_args()

    report = build_report(args.start)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_text(report), end="")


if __name__ == "__main__":
    main()
