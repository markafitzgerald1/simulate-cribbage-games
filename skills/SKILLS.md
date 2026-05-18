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
7. Run the required checks from `AGENTS.md`, or record why a check was skipped.
8. Update `README.md`, `AGENTS.md`, and this file together when shared workflow
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
through `coverage`, type checks through `mypy`, duplicate-code checks through
PMD CPD, and lint checks through `pylint` and `flake8`.

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

Near the end of this section, observe these boundaries: do not lower coverage
requirements, remove quality checks, add broad ignore comments, or refactor the
legacy `simulate_cribbage_games.py` dependency. Do not replace mathematical
simulation with subjective heuristics. Do not build on untested legacy behavior
or skip end-to-end smoke coverage for code changes.
