# AICSbench data

Benchmark runs submitted to [AICSbench](https://github.com/aicsbench/aicsbench),
the open benchmark for AI coding agents across languages and frameworks.
The public site, [aicsbench/web](https://github.com/aicsbench/web), is built
from this repository.

## What is here

| Path | Purpose |
| --- | --- |
| `submissions/<task_id>/<run_id>/` | One bundle per run, as written by `aicsbench submit` ([format](https://github.com/aicsbench/aicsbench/blob/main/docs/phase-5/schemas.md#submission-bundle)). |
| `verified-runs.txt` | Run IDs the maintainers verified, one per line. Default rankings show verified runs only. |
| `maintainers.txt` | GitHub logins allowed to change anything outside `submissions/`. |
| `export` branch | The site export, rebuilt by CI on every merge to `main`. Do not edit it. |

## How to submit

1. Run the benchmark, then submit the run:
   `aicsbench submit --run <run_id>` (add `--with-logs` to include logs; read
   them first). It validates the bundle and, with the GitHub CLI (`gh`)
   installed and logged in, forks this repository and opens the pull request
   for you.
2. To open the pull request by hand instead, write the bundle with
   `aicsbench submit --run <run_id> --out <directory>`, copy
   `<directory>/submissions/<task_id>/<run_id>/` into a fork of this
   repository, and open a pull request that **adds** that folder and nothing
   else. Either way, fill in the checklist in the pull request template.
3. Two checks must pass:
   - **validate** checks the bundle (layout, hashes, task version, secret scan,
     duplicates) and builds the site export as a smoke test;
   - **guard** checks which files changed: submissions are append-only, and only
     maintainers may change files outside `submissions/`.

A merged bundle is never edited or deleted. To correct a run, submit a new run.
Logs are optional; runs with logs get a "logs available" badge.

## Licence

Submitted result data (everything under `submissions/` and the `export` branch)
is published under [Creative Commons Attribution 4.0 International
(CC BY 4.0)](LICENSE-DATA). Opening a submission pull request means you agree to
publish your data under that licence.

The code in this repository (workflows, scripts, tests) is under the
[MIT licence](LICENSE).
