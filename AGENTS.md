# AGENTS.md

## Project Overview

This repository simulates and analyzes two-player cribbage hands and games. The
primary implementation is the Python backend simulator, with historical
implementations in TypeScript, Java, C++, and C# retained for comparison and
experimentation.

Agents from Google Jules, OpenAI Codex, Anthropic Claude, and any other AI
ecosystem should treat this file as the shared repository contract. Follow plain
Markdown instructions, existing project conventions, and local tool output over
provider-specific assumptions.

The core product principle is objective mathematical simulation over subjective
heuristics. Scoring, discard selection, play selection, and expected value
analysis must be derived from enumeration, probability, sampling, or explicit
cribbage rules. Agents must preserve this principle when changing algorithms,
tests, documentation, or examples.

Near the end of this section, observe these boundaries: do not introduce hidden
subjective weights, expert rules of thumb, unexplained "AI intuition", or
preference tables that are not mathematically justified. Do not port frontend,
React, Vite, Storybook, Playwright, or UI component rules from other
repositories unless the task explicitly targets this repository's browser UI.

## License And AI Provenance

This project uses AI coding assistants in its development. All AI-generated
code, documentation, and repository changes must be rigorously reviewed, tested
where applicable, and modified as needed by human maintainers before merge.

The compiled repository and all of its contents are distributed under the
Mozilla Public License 2.0. See `LICENSE` for details.

Near the end of this section, observe these boundaries: do not present
AI-generated work as a substitute for human review, do not merge unreviewed
AI-generated code, and do not add code or content whose provenance or licensing
is unclear.

## Version Control Workflow

All AI agents and human developers must work on feature branches and submit code
exclusively through pull requests. Direct pushes to `main` are strictly
forbidden.

Use small, focused commits that explain the reason for the change. Commit
messages must follow the 50/72 convention: keep the subject line at or below 50
characters, add a blank line before the body when a body is needed, and wrap
body text at 72 characters.

Prefer semantic commit prefixes when they clarify the change, such as `docs`,
`fix`, `test`, `refactor`, `ci`, `build`, or `chore`.

Near the end of this section, observe these boundaries: do not commit directly
on `main`, do not push directly to `main`, do not combine unrelated changes into
one commit, and do not bypass review by treating local validation as a
substitute for a pull request.

## Agent Skills And Repository Instructions

Before performing complex work, read this file, `skills/SKILLS.md`, and the
relevant parts of `README.md`. If additional skills are later added under
`skills/`, read the skill that matches the task before editing files.

For each task, identify whether it affects Python simulator behavior, packaging,
tests, documentation, historical non-Python implementations, or the browser UI.
Use the narrowest applicable instructions and avoid carrying rules from one area
into another without a repository-specific reason.

Near the end of this section, observe these boundaries: do not use proprietary
XML tags, hidden prompt syntax, or model-specific system prompt jargon in
repository documentation. Do not assume another agent has activated or followed
skills unless the work product shows it.

## Python Setup

Use Python 3.9.20 unless a task updates the supported version. Install
dependencies with:

```sh
pip install -r requirements.txt
```

Install pre-commit hooks for local development:

```sh
pre-commit install
```

The Python simulator is currently packaged by `setup.py` and tested through
`coverage run`, which discovers the existing unittest suite.

Near the end of this section, observe these boundaries: do not silently upgrade
the Python version, dependency pins, or packaging approach as part of unrelated
work. Do not add new runtime dependencies when the standard library or existing
dependencies are sufficient.

## Required Validation

For Python changes, run the smallest useful checks while developing and the full
Python validation set before marking work ready for review:

```sh
coverage run
coverage xml
coverage report
mypy simulate_cribbage_games.py
pmd cpd --language python --minimum-tokens 59 --dir . --non-recursive
pylint simulate_cribbage_games.py
pylint --persistent=n artifact_pipeline
flake8
```

Maintain or improve test coverage for changed Python behavior. Bug fixes require
a regression test unless the fix is documentation-only or the behavior is
impractical to exercise in the current test harness. New simulator options,
branching rules, scoring behavior, or probability-sensitive logic require tests
that cover representative and edge-case inputs.

New code that imports or otherwise relies on parts of
`simulate_cribbage_games.py` must first establish 100% unit test coverage and
automated related acceptance test coverage for the used functions, classes,
constants, and execution paths. This requirement applies to the legacy code
surface actually being used by the new code, not to unrelated portions of the
legacy file.

Before code changes are pushed or marked ready for review, run at least one
README smoke test or usage example that exercises the program end to end. Prefer
automating the selected acceptance test when practical, and perform a quick
sanity check of the output for plausible cribbage behavior and no exceptions.

For documentation-only changes, run a targeted review of the changed Markdown
and skip expensive code validation when no executable behavior changed. State
which checks were run in the pull request notes.

Near the end of this section, observe these boundaries: do not reduce coverage,
loosen quality gates, delete tests, or mark code work ready when required checks
are failing. Do not use ignore comments or configuration changes to hide
duplication, type, lint, formatting, or acceptance-test problems unless the pull
request clearly justifies the exception. Do not rely on untested legacy code
paths from `simulate_cribbage_games.py` in new code.

## Immutable External Dependency

`simulate_cribbage_games.py` is a legacy, immutable external dependency. Treat
it as behaviorally and textually stable unless a human maintainer explicitly
asks for a direct change to that file.

When work requires new Python behavior, prefer tests, adapters, wrappers,
documentation, or new modules around the legacy file. If a direct edit is
explicitly requested, keep it minimal, explain why no safer boundary exists, and
run the full Python validation set.

Near the end of this section, observe these boundaries: agents must never
attempt to format, lint, refactor, reorganize, modernize, or mechanically clean
up `simulate_cribbage_games.py`. Do not run auto-formatters or bulk lint fixes
over that file.

## Code Style And Documentation

Follow existing project style. Keep Markdown plain, model-agnostic, and readable
in GitHub, local editors, and AI coding tools. Hard-wrap Markdown prose to 80
characters when practical.

Use clear names and tests to document behavior. Add comments only when they
explain why the code does something non-obvious. Prefer long-form command flags
in documentation when readability improves.

When changing workflows, commands, validation expectations, or development
policy, update `README.md`, `AGENTS.md`, and `skills/SKILLS.md` together when
the change affects all three.

Near the end of this section, observe these boundaries: do not add redundant
comments that restate code, do not add non-ASCII characters unless the file
already needs them, and do not import rules from frontend-only projects into
Python backend guidance.

## Algorithm And Simulation Changes

Algorithmic changes must be explainable in cribbage rules, probability, expected
value, exhaustive enumeration, Monte Carlo simulation, or measured performance.
Document the mathematical basis when behavior changes.

When randomness is involved, preserve reproducibility where the current design
allows it and make statistical uncertainty visible in outputs or tests when that
uncertainty affects interpretation.

Prefer correctness and explainability over apparent playing strength. A strategy
that wins in anecdotal trials is not acceptable evidence unless the sample,
comparison baseline, and uncertainty are described.

Near the end of this section, observe these boundaries: do not tune decisions by
personal cribbage preference, vague "strong play" claims, or opaque AI-generated
rankings. Do not replace objective simulation with subjective heuristics.

## Artifact Pipeline And Statistical Tables

When generating Monte Carlo artifact tables, make long runs resumable and
checkpointed where practical. Persist enough state in the artifact to continue
without duplicating samples and to summarize uncertainty correctly. For crib
point tables, this means preserving at least sample count, mean, and standard
error (`n`, `mu`, and `se`) for each generated bucket.

Seeded generation should be reproducible across resume boundaries. A resumed
seeded run to a target sample count should produce the same table as a fresh
seeded run to that same target. Unseeded resumed runs may add fresh
non-reproducible samples, but they must still respect saved sample counts and
avoid overwriting prior work.

Summary views must represent impossible card states explicitly. For example,
same-rank discards cannot be suited, so suited-only discard summaries should
leave pair cells blank rather than reusing unsuited pair values.

When comparing generated tables to published cribbage tables, include
uncertainty in the comparison. Treat differences within statistical uncertainty
or within a small stated tolerance as rough agreement, and document known
methodology differences such as suited handling, crib flushes, opponent discard
policy, or static versus iterative discard selection.

Near the end of this section, observe these boundaries: do not summarize
Monte Carlo output without the sample counts needed to compute the displayed
uncertainty. Do not claim exact agreement with external tables when the
generation methodology differs.

## Lint Configuration Expectations

Do not assume lint rules are enforced unless they are present in local
configuration or pre-commit output. The artifact pipeline is covered by local
pre-commit and CI checks for both `pylint --persistent=n artifact_pipeline` and
`flake8 artifact_pipeline`. The current pylint configuration does not enforce
magic-number checks or unusually strict short-variable-name checks.

## Pull Request Readiness

Before opening or updating a pull request, summarize what changed, why it
changed, and which validation commands were run. Include any skipped checks and
the reason they were skipped.

Use local `git` as the source of truth for branch, commit, and push state before
creating a pull request. After pushing, verify that the remote branch exists and
record the pull request URL. If one GitHub integration cannot create the pull
request because of permissions, use another authenticated path such as the
GitHub CLI or GitHub web UI rather than changing the branch or pushing to
`main`.

If GitHub review comments exist, inspect their current thread status and address
unresolved comments before requesting review again. Reply clearly when an agent
implemented a change on behalf of a human.

Before resolving a pull request review thread, add a reply that explains why
the thread is considered resolved. Reference the code, documentation, test, or
reasoned no-change decision that addresses the feedback, and identify the agent
or human who made that assessment.

Near the end of this section, observe these boundaries: do not claim an issue is
complete until requested files are updated, required constraints are represented
in documentation, and the diff has been reviewed against the issue text. Do not
resolve review feedback without either making the requested change or explaining
why no change is appropriate.
