#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INCLUDE_DIRS = ("backend", "frontend", "scripts", "tests", "fixtures", "docs", "deploy")
INCLUDE_FILES = ("README.md", ".gitignore")
RUNTIME_NAMES = {
    "sentinel_dev.sqlite3",
    "sentinel_dev_server.log",
    ".sentinel_dev_server.pid",
    ".env",
}
RUNTIME_SUFFIXES = (".sqlite3", ".db", ".log", ".pid", ".pyc")
IGNORED_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
    ".git",
    ".superpowers",
}
OS_METADATA_PREFIXES = ("._",)
SECRET_PATTERNS = [
    re.compile(r"MASSIVE_API_KEY=(?!replace_|\\.\\.\\.)\\S+", re.IGNORECASE),
    re.compile(r"SENTINEL_EMAIL_PASSWORD=(?!replace_|\\.\\.\\.)\\S+", re.IGNORECASE),
    re.compile(r"SENTINEL_TELEGRAM_BOT_TOKEN=(?!replace_|\\.\\.\\.)\\S+", re.IGNORECASE),
    re.compile(r"(api[_-]?key|bot[_-]?token|password)\\s*[:=]\\s*['\\\"]?(?!replace_|your_|secret|\\.\\.\\.)[A-Za-z0-9_\\-]{24,}", re.IGNORECASE),
]


def should_skip(path: Path) -> bool:
    parts = set(path.relative_to(ROOT).parts)
    return bool(parts & IGNORED_PARTS)


def is_os_metadata(path: Path) -> bool:
    return path.name.startswith(OS_METADATA_PREFIXES)


def upload_files() -> list[Path]:
    files: list[Path] = []
    for filename in INCLUDE_FILES:
        path = ROOT / filename
        if path.exists():
            files.append(path)
    for dirname in INCLUDE_DIRS:
        base = ROOT / dirname
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or should_skip(path):
                continue
            if path.name in RUNTIME_NAMES or path.suffix in RUNTIME_SUFFIXES:
                continue
            files.append(path)
    return sorted(set(files))


def find_os_metadata_files() -> list[Path]:
    offenders = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or should_skip(path):
            continue
        if is_os_metadata(path):
            offenders.append(path)
    return sorted(offenders)


def find_runtime_files() -> list[Path]:
    offenders = []
    for path in ROOT.iterdir():
        if path.name in RUNTIME_NAMES or path.suffix in RUNTIME_SUFFIXES:
            offenders.append(path)
    return sorted(offenders)


def scan_secrets(files: list[Path]) -> list[str]:
    findings = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(f"{path.relative_to(ROOT)}:{lineno}: possible secret")
    return findings


def main() -> int:
    files = upload_files()
    os_metadata = find_os_metadata_files()
    if os_metadata:
        print("Upload package validation failed: OS metadata files found.", file=sys.stderr)
        for path in os_metadata:
            print(path.relative_to(ROOT), file=sys.stderr)
        return 1

    findings = scan_secrets(files)
    if findings:
        print("Upload package validation failed: possible secrets found.", file=sys.stderr)
        for finding in findings:
            print(finding, file=sys.stderr)
        return 1

    print("Upload package validation passed.")
    print("Files/folders to upload manually:")
    for item in INCLUDE_FILES + INCLUDE_DIRS:
        if (ROOT / item).exists():
            print(f"  {item}")
    runtime = find_runtime_files()
    if runtime:
        print("Runtime files present locally and excluded by .gitignore: %s" % len(runtime))
    print("Validated source file count: %s" % len(files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
