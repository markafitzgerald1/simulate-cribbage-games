# Skills

This directory contains repository-local guidance for AI agents and human
developers. Read `AGENTS.md` first, then read this file before complex work.

## Current Skills

No task-specific skill files are required for this repository yet. Until more
skills are added, use the validation and governance checklist below as the
default skill for documentation and Python backend work.

## Default Validation Skill

1. Identify whether the change affects documentation only, Python simulator
   behavior, packaging, tests, historical implementations, or the browser UI.
2. For Python behavior changes, add or update tests near the changed behavior.
3. Preserve objective mathematical simulation over subjective heuristics.
4. Keep `simulate_cribbage_games.py` immutable unless a human maintainer
   explicitly requests a direct edit.
5. If new code imports or relies on legacy `simulate_cribbage_games.py`
   behavior, prove the used legacy surface with 100% unit coverage and related
   automated acceptance coverage before relying on it.
6. Run at least one README smoke test or usage example for code changes, and
   sanity-check the output before review.
7. Run `npm run spellcheck` with Node.js 18 or newer for Python, script,
   Markdown, and repository instruction changes. Add only real project/domain
   words to `cspell.json`; rename opaque abbreviations or unpronounceable
   identifiers instead of allowlisting them. Run `npm ci --ignore-scripts`
   before `pre-commit install` so the local cspell hook can find its npm
   dependency.
8. Run the required checks from `AGENTS.md`, or record why a check was skipped.
9. For long-running Monte Carlo artifact generation, preserve resumability,
   checkpoint progress periodically, and keep sample counts with means and
   standard errors so summary tables can show uncertainty honestly.
10. When randomness is seedable, make resumed seeded runs deterministic by
   cumulative sample index or another explicit non-duplicating scheme. Persist
   seed metadata and reject resume attempts that would mix seeded and unseeded
   runs or different seed values.
11. When summarizing card tables, represent impossible states explicitly rather
   than filling them from a nearby valid state. For example, same-rank discards
   are never suited.
12. Do not assume lint rules such as magic-number checks or strict short-name
   checks exist unless local configuration or pre-commit output shows them.
13. When publishing, verify the pushed branch and pull request URL. If a GitHub
   integration cannot create the PR, use another authenticated path instead of
   changing the branch or bypassing review.
14. Before resolving a pull request review thread, reply with why the feedback is
   considered resolved and identify the agent or human making that assessment.
15. Update `README.md`, `AGENTS.md`, and this file together when shared workflow
   guidance changes.

## Skill Authoring Rules

Future skills should be written in plain, model-agnostic Markdown. Each skill
should state when it applies, what files or commands it covers, what validation
is required, and what output should be left for reviewers.

Prefer ecosystem-wide instructions that Google Jules, OpenAI Codex, Anthropic
Claude, and other agents can all understand. Keep provider-specific usage notes
out of repository governance unless they are essential to a concrete workflow.

Near the end of this section, observe these boundaries: do not add proprietary
XML tags, hidden prompt syntax, model-specific system prompt jargon, or
frontend-only rules to repository-wide skills. Do not create a skill that
permits direct pushes to `main` or bypasses pull request review.

## Python Backend Guardrails

Python backend work must preserve existing validation expectations: unit tests
through `coverage`, type checks through `mypy`, duplicate-code and lint checks
through `pylint` and `flake8`. The immutable legacy simulator must pass
`pylint --persistent=n --disable=all --enable=duplicate-code
simulate_cribbage_games.py` as a pre-push similarities gate. Artifact pipeline
Python code must pass both `pylint --persistent=n artifact_pipeline` and
`flake8 artifact_pipeline` locally and in CI.

Python backend, script, Markdown, and repository-instruction changes should
also pass `npm run spellcheck`. Treat cspell findings in identifiers as naming
feedback first: if a short or unpronounceable fragment is not a real project
term, rename it rather than adding it to `cspell.json`.

Exact analytical artifact-pipeline integration tests are opt-in locally because
they solve full discard-policy equilibria and are too slow for routine
pre-push. Run them before marking analytical math changes ready, and in CI,
with `coverage run --append scripts/run_slow_analytical_tests.py` after the
fast artifact test run, followed by `coverage report --fail-under=100 -m
--include='artifact_pipeline/*'`. CI may run named slow-test groups such as
`hessel-compat`, `zero-weights-coverage`, `support-dynamic-hessel`,
`historical-true-nobs`, and `historical-flat-nobs` in parallel and combine their
coverage data with the fast artifact coverage file before the 100%
artifact-pipeline coverage report.

Exact analytical test coverage should be as small as the behavior under review
allows. Full convergence is appropriate for published artifact generation and
for explicitly expensive CI gates, but regression tests can often use smaller
deterministic cases or paired statistical comparisons with a documented minimum
sample count and confidence threshold. If a comparison uses
`simulate_cribbage_games.py`, first cover every used legacy path as required by
`AGENTS.md`.

For analytical crib-table work, keep model claims precise. Deterministic
enumeration inside the rank/suit-free analytical model is exact for that model,
but iterative best response remains an iterative policy convergence process,
not a closed-form global proof. When dampening is used, preserve honest
measured statistics (`n`, `mu`, `se`) separately from policy values
(`policy_mu`, `policy_se`): reports should use measured values, while policy
selection and convergence checks may use dampened policy values when those are
the values that drive the next generation.

Convergence checks must require the expected conditional coverage. Missing
discard pair, player role, or starter-rank buckets should block finite
convergence claims unless the test or artifact explicitly documents a smaller
coverage surface.

Generated crib artifacts intended for browser-hosted TypeScript consumers, such
as `cribbage-trainer`, should be treated as the dependency boundary. Browser
code cannot call the Python solver directly, so either encode needed
conditional values in the artifact or reimplement runtime adjustments in
TypeScript with Python-generated golden tests.

Coverage must not decrease as a result of code changes. New simulator behavior
must include focused tests, especially for cribbage scoring, discard selection,
play selection, game-state transitions, and command-line options.

When new code uses the legacy simulator file, coverage expectations are stricter
for the used surface: every imported or relied-on function, class, constant, and
execution path from `simulate_cribbage_games.py` must have 100% unit coverage
and related automated acceptance coverage before the new code depends on it.

Every code change should run at least one acceptance-style README command from
the smoke tests or usage examples, ideally through automation, with a quick
human sanity check of the resulting output.

Artifact pipeline changes that produce statistical tables should include
focused tests for resume behavior, seeded reproducibility, checkpoint output,
summary-table formatting, and impossible card states such as suited pairs.

When publishing or updating a pull request, avoid force-pushing once review
comments exist unless a human maintainer explicitly requests rewritten history.
Attribute AI-written PR prose and comments to the agent, and avoid manual
hard-wrapping in GitHub-rendered PR descriptions or comments.

Near the end of this section, observe these boundaries: do not lower coverage
requirements, remove quality checks, add broad ignore comments, or refactor the
legacy `simulate_cribbage_games.py` dependency. Do not replace mathematical
simulation with subjective heuristics. Do not build on untested legacy behavior
or skip end-to-end smoke coverage for code changes.
