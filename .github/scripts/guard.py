"""File-and-author rules for pull requests to aicsbench/data.

Runs from the base branch on ``pull_request_target`` (``.github/workflows/guard.yml``)
and never reads or executes anything from the pull request. File names come from
the GitHub API and are treated as data only.

Rules (docs/phase-5/tasks/06-data-repo.md in aicsbench/aicsbench):

- the file list must be complete: fewer than 3,000 entries (the API's cap) and
  exactly as many as the PR's ``changed_files``; an incomplete list is never judged;
- under ``submissions/`` only additions are allowed;
- ``verified-runs.txt``, ``maintainers.txt``, ``CODEOWNERS`` and ``.github/`` may
  only be changed by a maintainer listed in the base branch's ``maintainers.txt``;
- a non-maintainer may not change anything outside ``submissions/``.

CLI::

    guard.py --files FILES.jsonl --pull PULL.json [--pull-after PULL.json]
             [--head-sha SHA] --maintainers maintainers.txt

``FILES.jsonl`` holds one JSON object per line with ``filename``, ``status`` and
``previous_filename`` (``gh api --paginate .../files --jq '.[] | {...}'``).
``PULL.json`` is the pull request object (``gh api .../pulls/N``); its
``user.login`` is the author and ``changed_files`` the expected file count.
Exit status 0 means pass, 1 means refused, 2 means bad input.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

API_FILE_LIMIT = 3000
SUBMISSIONS = "submissions/"
PROTECTED_FILES = frozenset({"verified-runs.txt", "maintainers.txt", "CODEOWNERS"})
PROTECTED_PREFIXES = (".github/",)


def parse_maintainers(text: str) -> set[str]:
    """GitHub logins, one per line; blank lines and ``#`` comments are skipped."""
    logins = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip().lstrip("@")
        if line:
            logins.add(line.casefold())
    return logins


def is_protected(path: str) -> bool:
    return path in PROTECTED_FILES or path.startswith(PROTECTED_PREFIXES)


def judge(
    files: list[Mapping[str, object]],
    *,
    author: str,
    maintainers: Iterable[str],
    changed_files: int,
) -> list[str]:
    """Reasons to refuse the pull request; an empty list means it passes."""
    if len(files) >= API_FILE_LIMIT:
        return [
            f"the file list has {len(files)} entries; GitHub lists at most {API_FILE_LIMIT}, "
            "so it may be incomplete and is not judged"
        ]
    if len(files) != changed_files:
        return [
            f"the file list has {len(files)} entries but the pull request changes "
            f"{changed_files} files; an incomplete list is not judged"
        ]

    is_maintainer = author.casefold() in {m.casefold() for m in maintainers}
    problems: list[str] = []
    for entry in files:
        filename = entry.get("filename")
        status = entry.get("status")
        previous = entry.get("previous_filename")
        if not isinstance(filename, str) or not isinstance(status, str):
            problems.append(f"malformed file entry: {json.dumps(entry, default=str)}")
            continue
        paths = [filename] + ([previous] if isinstance(previous, str) and previous else [])
        shown = f"{previous} -> {filename}" if len(paths) == 2 else filename

        if status != "added" and any(p.startswith(SUBMISSIONS) for p in paths):
            problems.append(
                f"{shown}: '{status}' under {SUBMISSIONS}; submissions are append-only, "
                "only new files may be added"
            )
        if is_maintainer:
            continue
        if any(is_protected(p) for p in paths):
            problems.append(
                f"{shown}: only a maintainer listed in the base branch's maintainers.txt "
                f"may change this file; '{author}' is not listed"
            )
        elif any(not p.startswith(SUBMISSIONS) for p in paths):
            problems.append(
                f"{shown}: outside {SUBMISSIONS}; only maintainers may change other files"
            )
    return problems


def _load_json(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--files", type=Path, required=True)
    parser.add_argument("--pull", type=Path, required=True)
    parser.add_argument("--pull-after", type=Path)
    parser.add_argument("--head-sha")
    parser.add_argument("--maintainers", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        pull = _load_json(args.pull)
        files = [
            json.loads(line)
            for line in args.files.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        maintainers = parse_maintainers(args.maintainers.read_text(encoding="utf-8"))
        author = pull["user"]["login"]  # type: ignore[index]
        changed_files = pull["changed_files"]
        if not isinstance(author, str) or not isinstance(changed_files, int):
            raise ValueError("pull request has no user.login or changed_files")
        heads = [pull["head"]["sha"]]  # type: ignore[index]
        if args.pull_after:
            heads.append(_load_json(args.pull_after)["head"]["sha"])  # type: ignore[index]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"guard: bad input: {exc}", file=sys.stderr)
        return 2

    expected = [args.head_sha] if args.head_sha else []
    if len(set(heads + expected)) != 1:
        print(
            "guard: the pull request's head changed while its files were listed "
            f"({', '.join(dict.fromkeys(heads + expected))}); a newer run judges it",
            file=sys.stderr,
        )
        return 1

    problems = judge(files, author=author, maintainers=maintainers, changed_files=changed_files)
    for problem in problems:
        print(f"guard: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"guard: ok, {len(files)} file(s) from '{author}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
