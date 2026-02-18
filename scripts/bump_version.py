"""Bump the app version stored in VERSION."""

from __future__ import annotations

from pathlib import Path
import argparse
import re


VERSION_FILE = Path("VERSION")
VERSION_PATTERN = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?$")


def parse_version(raw: str) -> tuple[int, int, int]:
    match = VERSION_PATTERN.match(raw.strip())
    if not match:
        raise ValueError(f"Invalid version format: {raw}")
    major = int(match.group(1) or 0)
    minor = int(match.group(2) or 0)
    patch = int(match.group(3) or 0)
    return major, minor, patch


def format_version(major: int, minor: int, patch: int) -> str:
    return f"{major}.{minor}.{patch}"


def bump_version(raw: str, mode: str) -> str:
    major, minor, patch = parse_version(raw)
    if mode == "major":
        return format_version(major + 1, 0, 0)
    if mode == "minor":
        return format_version(major, minor + 1, 0)
    if mode == "patch":
        return format_version(major, minor, patch + 1)
    raise ValueError(f"Unknown bump mode: {mode}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bump VERSION file")
    parser.add_argument("--mode", choices=["major", "minor", "patch"], default="patch")
    parser.add_argument("--set", dest="set_version")
    args = parser.parse_args()

    if args.set_version:
        new_version = args.set_version.strip()
    else:
        if not VERSION_FILE.exists():
            raise SystemExit("VERSION file not found.")
        current = VERSION_FILE.read_text(encoding="utf-8").strip()
        new_version = bump_version(current, args.mode)

    VERSION_FILE.write_text(new_version + "\n", encoding="utf-8")
    print(new_version)


if __name__ == "__main__":
    main()
