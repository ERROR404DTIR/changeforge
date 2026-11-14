#!/usr/bin/env python3
"""ChangeForge: Conventional Commits, changelog generation and semantic versioning.

Run directly with Python; the project uses only the standard library.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Optional

__version__ = "1.0.0"
HEADER = re.compile(r"^(?P<type>[a-z][a-z0-9-]*)(?:\((?P<scope>[^()\r\n]+)\))?(?P<breaking>!)?: (?P<description>.+)$")
SECTIONS = {
    "feat": "Features",
    "fix": "Fixes",
    "perf": "Performance",
    "refactor": "Refactoring",
    "docs": "Documentation",
    "build": "Build",
    "ci": "CI",
    "test": "Tests",
}

class ChangeForgeError(Exception):
    pass

def git(*args: str, check: bool = True) -> str:
    p = subprocess.run(["git", *args], text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, check=False)
    if check and p.returncode:
        raise ChangeForgeError(p.stderr.strip() or f"git {' '.join(args)} failed")
    return p.stdout.strip()

def parse_commit(message: str) -> Optional[dict]:
    lines = message.strip().splitlines()
    if not lines:
        return None
    m = HEADER.match(lines[0].strip())
    if not m:
        return None
    breaking = bool(m.group("breaking")) or any(
        re.match(r"^BREAKING CHANGE:\s*\S", line, re.I) for line in lines[1:]
    )
    return {**m.groupdict(), "breaking": breaking, "body": "\n".join(lines[1:]).strip()}

def lint_message(message: str) -> list[str]:
    lines = message.rstrip("\n").splitlines()
    if not lines or not lines[0].strip():
        return ["commit message is empty"]
    errors = []
    first = lines[0]
    parsed = parse_commit(message)
    if not parsed:
        errors.append("header must follow: type(scope): description")
        return errors
    if len(first) > 100:
        errors.append(f"header is {len(first)} characters; keep it at 100 or fewer")
    if first.endswith("."):
        errors.append("header must not end with a period")
    if parsed["description"][0].islower() is False and parsed["description"][0].isalpha():
        errors.append("description should start with a lowercase letter")
    return errors

def read_commits(revision: Optional[str] = None) -> list[dict]:
    args = ["log", "--no-merges", "--format=%H%x1f%s%x1f%b%x1e"]
    if revision:
        args.append(revision)
    raw = git(*args)
    result = []
    for record in raw.split("\x1e"):
        record = record.strip()
        if not record:
            continue
        parts = record.split("\x1f", 2)
        if len(parts) != 3:
            continue
        sha, subject, body = parts
        parsed = parse_commit(subject + ("\n\n" + body if body else ""))
        if parsed:
            parsed["sha"] = sha
            parsed["subject"] = subject
            result.append(parsed)
    return result

def latest_tag() -> Optional[str]:
    value = git("describe", "--tags", "--abbrev=0", check=False)
    return value or None

def version_tuple(value: str) -> tuple[int, int, int]:
    m = re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value.strip())
    if not m:
        raise ChangeForgeError(f"invalid semantic version: {value!r}")
    return tuple(map(int, m.groups()))

def next_version(current: str, commits: Iterable[dict]) -> str:
    major, minor, patch = version_tuple(current)
    items = list(commits)
    if any(c["breaking"] for c in items):
        major += 1
        minor = patch = 0
    elif any(c["type"] == "feat" for c in items):
        minor += 1
        patch = 0
    elif any(c["type"] in ("fix", "perf") for c in items):
        patch += 1
    return f"{major}.{minor}.{patch}"

def render_changelog(commits: list[dict], version: str = "Unreleased") -> str:
    groups: dict[str, list[str]] = {}
    breaking = []
    for c in commits:
        kind = c["type"]
        title = SECTIONS.get(kind, "Other")
        label = f"{c['scope']}: " if c.get("scope") else ""
        entry = f"- {label}{c['description']} ({c['sha'][:7]})"
        groups.setdefault(title, []).append(entry)
        if c["breaking"]:
            breaking.append(entry)
    order = ["Features", "Fixes", "Performance", "Refactoring", "Documentation",
             "Build", "CI", "Tests", "Other"]
    out = [f"## {version}", ""]
    if breaking:
        out += ["### BREAKING CHANGES", "", *breaking, ""]
    for title in order:
        if title in groups:
            out += [f"### {title}", "", *groups[title], ""]
    return "\n".join(out).rstrip() + "\n"

def command_lint(args: argparse.Namespace) -> int:
    try:
        message = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    except OSError as exc:
        print(f"changeforge: {exc}", file=sys.stderr)
        return 2
    errors = lint_message(message)
    if errors:
        for error in errors:
            print(f"✗ {error}", file=sys.stderr)
        return 1
    print("✓ Conventional Commit message")
    return 0

def command_changelog(args: argparse.Namespace) -> int:
    try:
        rev = args.since or (f"{latest_tag()}..HEAD" if latest_tag() else "HEAD")
        commits = read_commits(rev)
        content = render_changelog(commits, args.version or "Unreleased")
        if args.output:
            target = Path(args.output)
            if target.exists() and not args.force:
                raise ChangeForgeError(f"{target} exists; use --force to overwrite")
            target.write_text(content, encoding="utf-8")
        else:
            print(content, end="")
        return 0
    except (ChangeForgeError, OSError) as exc:
        print(f"changeforge: {exc}", file=sys.stderr)
        return 2

def command_bump(args: argparse.Namespace) -> int:
    try:
        rev = args.since or (f"{latest_tag()}..HEAD" if latest_tag() else "HEAD")
        current = args.current or (latest_tag() or "0.1.0").lstrip("v")
        result = next_version(current, read_commits(rev))
        print(result)
        return 0
    except ChangeForgeError as exc:
        print(f"changeforge: {exc}", file=sys.stderr)
        return 2

def command_hook(args: argparse.Namespace) -> int:
    try:
        root = Path(git("rev-parse", "--show-toplevel"))
        hook = root / ".git" / "hooks" / "commit-msg"
        if not (root / ".git").is_dir():
            raise ChangeForgeError("worktrees and non-directory .git files are not supported yet")
        if hook.exists() and not args.force:
            raise ChangeForgeError(f"{hook} already exists; use --force to replace it")
        script = Path(__file__).resolve()
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\nexec " + repr(sys.executable) + " " + repr(str(script))
                        + " lint --file \"$1\"\n", encoding="utf-8")
        hook.chmod(0o755)
        print(f"Installed commit-msg hook: {hook}")
        return 0
    except (ChangeForgeError, OSError) as exc:
        print(f"changeforge: {exc}", file=sys.stderr)
        return 2

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="changeforge", description="Conventional Commits and release helper.")
    p.add_argument("-V", "--version", action="version", version=f"ChangeForge {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    lint = sub.add_parser("lint", help="Validate a Conventional Commit message.")
    lint.add_argument("--file", help="Read the commit message from a file (default: stdin).")
    lint.set_defaults(func=command_lint)
    log = sub.add_parser("changelog", help="Generate a Markdown changelog from git history.")
    log.add_argument("--since", help="Git revision range, e.g. v1.0.0..HEAD.")
    log.add_argument("--version", help="Heading for the generated section.")
    log.add_argument("-o", "--output", help="Write to a file instead of stdout.")
    log.add_argument("--force", action="store_true", help="Allow overwriting the output file.")
    log.set_defaults(func=command_changelog)
    bump = sub.add_parser("bump", help="Calculate the next semantic version.")
    bump.add_argument("--current", help="Current version (default: latest git tag or 0.1.0).")
    bump.add_argument("--since", help="Git revision range to inspect.")
    bump.set_defaults(func=command_bump)
    hook = sub.add_parser("install-hook", help="Install a local commit-msg validation hook.")
    hook.add_argument("--force", action="store_true", help="Replace an existing commit-msg hook.")
    hook.set_defaults(func=command_hook)
    return p

def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    raise SystemExit(main())
