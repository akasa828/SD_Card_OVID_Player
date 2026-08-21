#!/usr/bin/env python3
"""Validate commit subjects without third-party dependencies."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys


ZERO_SHA = "0" * 40
CONVENTIONAL_RE = re.compile(
    r"^(?:feat|fix|refactor|perf|docs|test|build|ci|chore|revert)"
    r"(?:\([a-z0-9][a-z0-9-]*\))?!?: [A-Za-z0-9].+$"
)


def validate_subject(subject: str) -> list[str]:
    errors = []
    if subject.endswith("."):
        errors.append("subject must not end with a period")
    if not subject.isascii():
        errors.append("subject must use ASCII English text")
    if (not CONVENTIONAL_RE.fullmatch(subject)
            and not subject.startswith("Merge ")
            and not re.fullmatch(r'Revert ".+"', subject)):
        errors.append(
            "expected type(scope): imperative summary "
            "(scope is optional)"
        )
    return errors


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def commit_range(base: str, head: str) -> str:
    if not base or base == ZERO_SHA:
        return head
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base, head],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return f"{base}..{head}" if ancestor.returncode == 0 else head


def read_commits(base: str, head: str) -> list[tuple[str, str]]:
    revision = commit_range(base, head)
    output = git("log", "--reverse", "--format=%H%x00%s", revision)
    commits = []
    for line in output.splitlines():
        if not line:
            continue
        sha, subject = line.split("\0", 1)
        commits.append((sha, subject))
    return commits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)

    failures = []
    for sha, subject in read_commits(args.base, args.head):
        errors = validate_subject(subject)
        if errors:
            failures.append((sha, subject, errors))

    if failures:
        for sha, subject, errors in failures:
            print(f"{sha[:12]}  {subject}", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
        return 1

    print("All commit subjects follow the repository convention.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
