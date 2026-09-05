"""Validate repository skills without reading private configuration or importing the app."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def validate(root: Path) -> tuple[list[str], int]:
    errors: list[str] = []
    paths = sorted(root.glob(".claude/skills/*/SKILL.md"))
    paths += sorted(root.glob(".grok/skills/*/SKILL.md"))
    if not paths:
        return ["No repository skills found"], 0
    names: set[str] = set()
    for path in paths:
        label = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        parts = text.split("---", 2)
        if len(parts) != 3 or parts[0].strip():
            errors.append(f"{label}: missing frontmatter")
            continue
        fields = {}
        for line in parts[1].splitlines():
            if ":" in line and not line.startswith(" "):
                key, value = line.split(":", 1)
                fields[key] = value.strip()
        name = fields.get("name", "")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
            errors.append(f"{label}: invalid name")
        if name != path.parent.name or name in names:
            errors.append(f"{label}: duplicate or mismatched name")
        names.add(name)
        if not fields.get("description"):
            errors.append(f"{label}: missing description")
        for target in LINK.findall(parts[2]):
            target = target.split("#", 1)[0]
            if not target or target.startswith(("https://", "http://", "mailto:")):
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.is_relative_to(root.resolve()) or not resolved.exists():
                errors.append(f"{label}: unresolved repository link: {target}")
    return errors, len(paths)


def main() -> int:
    errors, count = validate(ROOT)
    for error in errors:
        print(error, file=sys.stderr)
    print(f"{count} skills checked; {len(errors)} structural errors")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
