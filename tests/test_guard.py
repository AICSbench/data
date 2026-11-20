"""Tests for .github/scripts/guard.py and the trust boundary of guard.yml."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

_spec = importlib.util.spec_from_file_location("guard", ROOT / ".github" / "scripts" / "guard.py")
assert _spec and _spec.loader
guard = importlib.util.module_from_spec(_spec)
sys.modules["guard"] = guard
_spec.loader.exec_module(guard)

MAINTAINERS = {"dyaskur"}
BUNDLE = "submissions/task-management-api/run-001"


def added(path: str) -> dict[str, object]:
    return {"filename": path, "status": "added", "previous_filename": None}


def judge(files, author="contributor", maintainers=MAINTAINERS, changed_files=None):
    if changed_files is None:
        changed_files = len(files)
    return guard.judge(
        files, author=author, maintainers=maintainers, changed_files=changed_files
    )


# --- Rule: the list must be complete ---------------------------------------------------------


def test_refuses_a_list_of_3000_entries_even_from_a_maintainer():
    files = [added(f"{BUNDLE}/trials/t{i}.json") for i in range(3000)]
    problems = judge(files, author="dyaskur", changed_files=3000)
    assert len(problems) == 1 and "3000" in problems[0]


def test_accepts_2999_new_submission_files():
    files = [added(f"{BUNDLE}/trials/t{i}.json") for i in range(2999)]
    assert judge(files) == []


def test_refuses_a_list_shorter_than_changed_files():
    files = [added(f"{BUNDLE}/submission.json")]
    problems = judge(files, changed_files=2)
    assert len(problems) == 1 and "incomplete" in problems[0]


def test_refuses_a_list_longer_than_changed_files():
    files = [added(f"{BUNDLE}/submission.json"), added(f"{BUNDLE}/manifest.json")]
    assert judge(files, changed_files=1) != []


# --- Rule: submissions are append-only -------------------------------------------------------


def test_contributor_may_add_a_submission():
    files = [
        added(f"{BUNDLE}/submission.json"),
        added(f"{BUNDLE}/manifest.json"),
        added(f"{BUNDLE}/trials/trial-001.json"),
    ]
    assert judge(files) == []


@pytest.mark.parametrize("status", ["modified", "removed", "changed", "copied", "unchanged"])
@pytest.mark.parametrize("author", ["contributor", "dyaskur"])
def test_non_additions_under_submissions_are_refused_for_everyone(status, author):
    files = [{"filename": f"{BUNDLE}/manifest.json", "status": status}]
    problems = judge(files, author=author)
    assert len(problems) == 1 and "append-only" in problems[0]


@pytest.mark.parametrize("author", ["contributor", "dyaskur"])
def test_rename_within_submissions_is_refused(author):
    files = [
        {
            "filename": "submissions/task-management-api/run-002/manifest.json",
            "status": "renamed",
            "previous_filename": f"{BUNDLE}/manifest.json",
        }
    ]
    assert any("append-only" in p for p in judge(files, author=author))


def test_maintainer_renaming_a_file_out_of_submissions_is_refused():
    files = [
        {"filename": "archive/manifest.json", "status": "renamed",
         "previous_filename": f"{BUNDLE}/manifest.json"}
    ]
    assert any("append-only" in p for p in judge(files, author="dyaskur"))


def test_renaming_into_submissions_is_not_an_addition():
    files = [
        {"filename": f"{BUNDLE}/notes.json", "status": "renamed", "previous_filename": "notes.json"}
    ]
    problems = judge(files)
    assert any("append-only" in p for p in problems)
    assert any("outside" in p for p in problems)


# --- Rule: protected files need a maintainer -------------------------------------------------


PROTECTED = [
    "verified-runs.txt",
    "maintainers.txt",
    "CODEOWNERS",
    ".github/workflows/guard.yml",
    ".github/scripts/guard.py",
    ".github/pull_request_template.md",
]


@pytest.mark.parametrize("path", PROTECTED)
@pytest.mark.parametrize("status", ["added", "modified", "removed"])
def test_contributor_may_not_touch_protected_files(path, status):
    problems = judge([{"filename": path, "status": status}])
    assert len(problems) == 1 and "maintainer" in problems[0]


@pytest.mark.parametrize("path", PROTECTED)
def test_maintainer_may_change_protected_files(path):
    assert judge([{"filename": path, "status": "modified"}], author="dyaskur") == []


def test_maintainer_login_is_case_insensitive():
    assert judge([{"filename": "verified-runs.txt", "status": "modified"}], author="DYaskur") == []


def test_a_pr_cannot_add_its_own_author_to_maintainers():
    # The maintainer list comes from the base branch, so the PR's edit does not count.
    files = [{"filename": "maintainers.txt", "status": "modified"}]
    assert judge(files, author="mallory", maintainers={"dyaskur"}) != []


def test_renaming_a_protected_file_away_is_refused():
    files = [{"filename": "submissions/x/y/z.json", "status": "renamed",
              "previous_filename": "verified-runs.txt"}]
    assert any("maintainer" in p for p in judge(files))


# --- Rule: non-maintainers stay inside submissions/ -------------------------------------------


@pytest.mark.parametrize(
    "path", ["README.md", "LICENSE-DATA", "tests/test_guard.py", "submissionsX/a.json",
             "submissions", "export/data/trials.json"]
)
def test_contributor_may_not_touch_files_outside_submissions(path):
    problems = judge([added(path)])
    assert len(problems) == 1 and "outside submissions/" in problems[0]


def test_maintainer_may_touch_other_files():
    assert judge([{"filename": "README.md", "status": "modified"}], author="dyaskur") == []


def test_one_bad_file_refuses_a_mixed_pr():
    files = [added(f"{BUNDLE}/submission.json"), added("README.md")]
    assert len(judge(files)) == 1


def test_malformed_entry_is_refused():
    assert judge([{"filename": None, "status": "added"}]) != []


def test_parse_maintainers_skips_comments_and_at_signs():
    assert guard.parse_maintainers("# owners\n@DYaskur\n\nother # note\n") == {"dyaskur", "other"}


def test_shipped_maintainers_file_lists_dyaskur():
    text = (ROOT / "maintainers.txt").read_text(encoding="utf-8")
    assert guard.parse_maintainers(text) == {"dyaskur"}


# --- CLI ---------------------------------------------------------------------------------------


def _cli(tmp_path, files, author="contributor", changed_files=None, head="a" * 40,
         after_head=None, head_sha=None):
    (tmp_path / "files.jsonl").write_text("".join(json.dumps(f) + "\n" for f in files))
    pull = {"user": {"login": author}, "head": {"sha": head},
            "changed_files": len(files) if changed_files is None else changed_files}
    (tmp_path / "pull.json").write_text(json.dumps(pull))
    (tmp_path / "after.json").write_text(json.dumps({**pull, "head": {"sha": after_head or head}}))
    (tmp_path / "maintainers.txt").write_text("dyaskur\n")
    args = ["--files", str(tmp_path / "files.jsonl"), "--pull", str(tmp_path / "pull.json"),
            "--pull-after", str(tmp_path / "after.json"),
            "--maintainers", str(tmp_path / "maintainers.txt")]
    if head_sha:
        args += ["--head-sha", head_sha]
    return guard.main(args)


def test_cli_passes_a_submission(tmp_path):
    assert _cli(tmp_path, [added(f"{BUNDLE}/submission.json")], head_sha="a" * 40) == 0


def test_cli_fails_on_a_rule(tmp_path):
    assert _cli(tmp_path, [added("README.md")]) == 1


def test_cli_fails_on_short_list(tmp_path):
    assert _cli(tmp_path, [added(f"{BUNDLE}/submission.json")], changed_files=5) == 1


def test_cli_fails_when_head_moves_while_listing(tmp_path):
    assert _cli(tmp_path, [added(f"{BUNDLE}/submission.json")], after_head="b" * 40) == 1


def test_cli_fails_when_event_head_differs(tmp_path):
    assert _cli(tmp_path, [added(f"{BUNDLE}/submission.json")], head_sha="c" * 40) == 1


def test_cli_rejects_bad_input(tmp_path):
    (tmp_path / "pull.json").write_text("[]")
    (tmp_path / "files.jsonl").write_text("")
    (tmp_path / "m.txt").write_text("")
    assert guard.main(["--files", str(tmp_path / "files.jsonl"), "--pull",
                       str(tmp_path / "pull.json"), "--maintainers", str(tmp_path / "m.txt")]) == 2


# --- guard.yml never runs PR content ----------------------------------------------------------


def _workflow(name):
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    data["on"] = data.pop(True, data.get("on"))  # YAML 1.1 reads `on` as true
    return data


def _steps(workflow):
    return [step for job in workflow["jobs"].values() for step in job.get("steps", [])]


PR_REFERENCE = re.compile(r"github\.(event\.pull_request|head_ref)|refs/pull/", re.I)


def test_guard_runs_on_pull_request_target_only():
    assert set(_workflow("guard.yml")["on"]) == {"pull_request_target"}


def test_guard_checks_out_the_base_branch_only():
    checkouts = [s for s in _steps(_workflow("guard.yml"))
                 if str(s.get("uses", "")).startswith("actions/checkout@")]
    assert len(checkouts) == 1
    with_ = checkouts[0].get("with", {})
    assert "ref" not in with_ and "repository" not in with_
    assert not PR_REFERENCE.search(json.dumps(with_))
    assert with_.get("persist-credentials") is False


def test_guard_runs_only_base_branch_files():
    for step in _steps(_workflow("guard.yml")):
        uses = step.get("uses")
        if uses:
            # Only pinned third-party actions, never a local action from the checkout.
            assert not uses.startswith("./") and re.search(r"@[0-9a-f]{40}$", uses), uses
        run = step.get("run", "")
        if run:
            # PR values reach steps only through env as data, never interpolated into scripts.
            assert "${{" not in run, step
            for line in run.splitlines():
                for cmd in re.findall(r"\b(?:python3?|bash|sh|source|node)\s+(\S+)", line):
                    assert cmd in {".github/scripts/guard.py", "-c"} or cmd.startswith("-"), line
            assert "git fetch" not in run and "git checkout" not in run and "pip install" not in run


def test_guard_permissions_are_read_only():
    wf = _workflow("guard.yml")
    assert wf["permissions"] == {}
    for job in wf["jobs"].values():
        assert job["permissions"] == {"contents": "read", "pull-requests": "read"}


# --- All workflows: pinned actions, least privilege, token placement --------------------------


# GitHub runs both extensions, so both must face the checks below.
ALL = sorted(p.name for p in WORKFLOWS.iterdir() if p.suffix in {".yml", ".yaml"})


@pytest.mark.parametrize("name", ALL)
def test_actions_are_pinned_to_a_full_sha_with_a_version_comment(name):
    for line in (WORKFLOWS / name).read_text(encoding="utf-8").splitlines():
        m = re.search(r"uses:\s*(\S+)(.*)", line)
        if m:
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", m.group(1)), line
            assert re.search(r"#\s*v\d+\.\d+\.\d+", m.group(2)), line


# Every workflow and job, with exactly the permissions it may have. A new job or a
# widened permission fails here until it is reviewed and added.
PERMISSIONS = {
    "guard.yml": {"guard": {"contents": "read", "pull-requests": "read"}},
    "validate.yml": {"validate": {"contents": "read"}},
    "test-guard.yml": {"test-guard": {"contents": "read"}},
    "publish.yml": {"export": {"contents": "write"}, "notify-web": {}},
}


def test_workflows_are_the_reviewed_set():
    assert set(ALL) == set(PERMISSIONS)


@pytest.mark.parametrize("name", ALL)
def test_job_permissions_match_the_allowlist(name):
    wf = _workflow(name)
    assert wf["permissions"] == {}
    assert {job: spec.get("permissions") for job, spec in wf["jobs"].items()} == PERMISSIONS[name]


def test_web_dispatch_token_only_in_notify_web():
    for name in ALL:
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        if name != "publish.yml":
            assert "WEB_DISPATCH_TOKEN" not in text and not re.search(r"\bsecrets\.\w", text), name
    wf = _workflow("publish.yml")
    # Workflow-level keys (env, defaults, ...) reach every job, so none may hold the token.
    outside_jobs = {key: value for key, value in wf.items() if key != "jobs"}
    assert "WEB_DISPATCH_TOKEN" not in json.dumps(outside_jobs)
    for job_name, job in wf["jobs"].items():
        found = "WEB_DISPATCH_TOKEN" in json.dumps(job)
        assert found == (job_name == "notify-web"), job_name


def test_publish_is_serialized():
    wf = _workflow("publish.yml")
    assert wf["concurrency"] == {"group": "publish", "cancel-in-progress": False, "queue": "max"}


@pytest.mark.parametrize("name", ["validate.yml", "test-guard.yml"])
def test_pull_request_workflows_are_read_only(name):
    for job in _workflow(name)["jobs"].values():
        assert job["permissions"] == {"contents": "read"}


def test_benchmark_ref_is_the_same_in_every_workflow():
    refs = {_workflow(n)["env"]["AICSBENCH_REF"] for n in ("validate.yml", "publish.yml")}
    assert len(refs) == 1 and re.fullmatch(r"[0-9a-f]{40}", refs.pop())
