#!/usr/bin/env python3

import json
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse


ROOT = Path(__file__).resolve().parent.parent
VIEWER_BASE = "https://pwright.github.io/blockscape/?load="
RAW_BASE = (
    "https://raw.githubusercontent.com/pwright/"
    "blockscape-maps/refs/heads/main/renaissance/"
)


def build_external(filename: str) -> str:
    return f"{VIEWER_BASE}{quote(f'{RAW_BASE}{filename}', safe='')}"


def extract_filename_from_external(external: object) -> str | None:
    if not isinstance(external, str) or not external:
        return None

    if external.startswith("?load="):
        filename = external.removeprefix("?load=")
        return filename if filename.endswith(".bs") else None

    parsed = urlparse(external)
    load_values = parse_qs(parsed.query).get("load")
    if not load_values:
        return None

    load_value = unquote(load_values[0])
    if load_value.endswith(".bs"):
        return Path(load_value).name

    return None


def walk(node, visit):
    if isinstance(node, dict):
        visit(node)
        for value in node.values():
            walk(value, visit)
    elif isinstance(node, list):
        for item in node:
            walk(item, visit)


def main() -> int:
    bs_files = sorted(ROOT.glob("*.bs"))
    filenames_by_stem = {path.stem: path.name for path in bs_files}
    updated_files = []

    for path in bs_files:
        data = json.loads(path.read_text())
        changed = False

        def visit(node):
            nonlocal changed
            item_id = node.get("id")
            target_filename = None
            if isinstance(item_id, str):
                target_filename = filenames_by_stem.get(item_id)
            if not target_filename:
                target_filename = extract_filename_from_external(node.get("external"))
            if not target_filename or target_filename == path.name:
                return

            external = build_external(target_filename)
            if node.get("external") != external:
                node["external"] = external
                changed = True

        walk(data, visit)

        if changed:
            path.write_text(json.dumps(data, indent=2) + "\n")
            updated_files.append(path.name)

    for filename in updated_files:
        print(filename)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
