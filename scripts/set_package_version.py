from __future__ import annotations

import argparse
import re
from pathlib import Path


def normalize_version(raw_version: str) -> str:
    version = raw_version.strip()
    if not version:
        raise ValueError("Version cannot be empty")
    if version.startswith("v"):
        version = version[1:]

    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z]+)?", version):
        raise ValueError(
            f"Invalid version '{raw_version}'. Expected semantic version like v1.0.1 or 1.0.1"
        )
    return version


def update_pyproject_version(pyproject_path: Path, version: str) -> None:
    text = pyproject_path.read_text(encoding="utf-8")
    updated_text, replacements = re.subn(
        r'(?m)^version\s*=\s*"[^"]+"\s*$',
        f'version = "{version}"',
        text,
        count=1,
    )

    if replacements != 1:
        raise RuntimeError("Could not find a unique 'version = \"...\"' entry in pyproject.toml")

    pyproject_path.write_text(updated_text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set package version in pyproject.toml from a release tag/input value"
    )
    parser.add_argument("raw_version", help="Version/tag value (e.g. v1.0.1 or 1.0.1)")
    parser.add_argument(
        "--pyproject",
        default="pyproject.toml",
        help="Path to pyproject.toml (default: pyproject.toml)",
    )
    args = parser.parse_args()

    version = normalize_version(args.raw_version)
    pyproject_path = Path(args.pyproject)

    if not pyproject_path.exists():
        raise FileNotFoundError(f"File not found: {pyproject_path}")

    update_pyproject_version(pyproject_path, version)
    print(f"Set package version to {version}")


if __name__ == "__main__":
    main()
