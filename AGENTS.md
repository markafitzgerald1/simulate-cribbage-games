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
substitute for a pull request. AI agents are permitted to commit using the
`--no-gpg-sign` flag when committing in sandboxed environments where local GPG
private keys are unavailable.

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

Use Python 3.14.4 unless a task updates the supported version. Install
dependencies with:

```sh
pip install -r requirements.txt
```

Install Node.js 18 or newer and npm development dependencies before installing
pre-commit hooks, because the local cspell hook runs through npm:

```sh
npm ci --ignore-scripts
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
coverage run -m unittest discover artifact_pipeline
coverage run --append scripts/run_slow_analytical_tests.py
coverage report --fail-under=100 -m --include='artifact_pipeline/*'
mypy simulate_cribbage_games.py artifact_pipeline
npm run spellcheck
pylint simulate_cribbage_games.py
pylint --persistent=n --disable=all --enable=duplicate-code simulate_cribbage_games.py
pylint --persistent=n artifact_pipeline
flake8
```

The default unittest discovery path intentionally skips exact analytical
integration tests that solve full discard-policy equilibria. Those tests are
required before marking artifact-pipeline math changes ready and in CI, but they
are too slow for the local pre-push hook. Run them explicitly with
`coverage run --append scripts/run_slow_analytical_tests.py` as shown above.
CI may shard these exact tests by passing group names such as `hessel-compat`,
`zero-weights-coverage`, `support-dynamic-hessel`, `historical-true-nobs`, and
`historical-flat-nobs`, then combine coverage data before enforcing 100%
artifact-pipeline coverage.

Exact analytical tests do not always need to prove full production-artifact
convergence. For test coverage, prefer the smallest deterministic or
statistically justified check that proves the changed behavior. If a test
asserts that one table or strategy beats another by simulation, use paired
comparisons where practical, require a meaningful minimum sample count before
early stopping, and make the confidence criterion explicit. Reserve full
long-running convergence for published artifact generation or CI gates that are
clearly documented as expensive.

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
For Python or core dependency upgrades, run the regression checking script
[scratch/verify_upgrade.py](scratch/verify_upgrade.py)
(passing the old and new Python binaries as arguments) to verify that simulated
game outputs and generated tables match 100% identically. (Note: Once full test
automation is complete under issue #37, this script may be retired.)

When validating upgrades or writing regression checkers, observe these rules:
- **Isolate execution environments:** Run checks in isolated temporary directories
  (configuring `cwd` and version-specific `PYTHONPATH`) to prevent SQLite cache
  databases (`diskcache`) or tallies database files (`shelve`/`dbm` shelves) from
  cross-contaminating runs or causing file access collisions.
- **Initialize DB shelves:** Ensure empty tally shelves are created/opened with
  write permissions (`flag="c"`) before running simulator checks, as read-only
  opens (`flag="r"`) will fail on clean checkouts where shelf files do not
  exist or are in an incompatible platform format.
- **Normalize stdout/stderr:** Strip or normalize elapsed times, speed metrics,
  or other runtime-dependent performance lines (using regex) before diffing.
- **Compare stderr and file outputs:** Always check `stderr` as well as stdout
  to capture deprecation warnings or diagnostics, and compare generated files
  directly rather than relying solely on CLI print logs.

For documentation-only changes, run a targeted review of the changed Markdown
and skip expensive code validation when no executable behavior changed. State
which checks were run in the pull request notes.

Near the end of this section, observe these boundaries: do not reduce coverage,
loosen quality gates, delete tests, or mark code work ready when required checks
are failing. Do not use ignore comments or configuration changes to hide
duplication, type, lint, formatting, or acceptance-test problems unless the pull
request clearly justifies the exception. Do not rely on untested legacy code
paths from `simulate_cribbage_games.py` in new code. Agents must never modify,
bypass, or disable local pre-commit hooks, CI configuration gates, or coverage
validation rules without explicit human maintainer consent.

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

When artifact-pipeline comparisons call into `simulate_cribbage_games.py`, first
add focused coverage for every legacy function, class, constant, and execution
path used by that comparison. Do not use full-game comparison harnesses as a
shortcut around the immutable-dependency coverage requirement.

## Code Style And Documentation

Follow existing project style. Keep Markdown plain, model-agnostic, and readable
in GitHub, local editors, and AI coding tools. Hard-wrap Markdown prose to 80
characters when practical.

Use clear names and tests to document behavior. Add comments only when they
explain why the code does something non-obvious. Prefer long-form command flags
in documentation when readability improves.

Run `npm run spellcheck` after changing Python code, scripts, Markdown, or
repository instructions. The cspell dictionary in `cspell.json` is intentionally
repo-specific: add domain words only after confirming they are real cribbage,
statistical, historical-table, tool, or project terms. Do not add opaque
abbreviations merely to silence the checker; rename short or unpronounceable
identifiers instead.

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
without duplicating samples, validate resume compatibility, and summarize
uncertainty correctly. For crib point tables, this means preserving at least
sample count, mean, and standard error (`n`, `mu`, and `se`) for each generated
bucket, plus seed and generation-method metadata for the file as a whole.

Seeded generation should be reproducible across resume boundaries. A resumed
seeded run to a target sample count should produce the same table as a fresh
seeded run to that same target. Unseeded resumed runs may add fresh
non-reproducible samples, but they must still respect saved sample counts,
preserve the unseeded metadata, reject later seeded resumes, and avoid
overwriting prior work.

Summary views must represent impossible card states explicitly. For example,
same-rank discards cannot be suited, so suited-only discard summaries should
leave pair cells blank rather than reusing unsuited pair values.

When comparing generated tables to published cribbage tables, include
uncertainty in the comparison. Treat differences within statistical uncertainty
or within a small stated tolerance as rough agreement, and document known
methodology differences such as suited handling, crib flushes, opponent discard
policy, or static versus iterative discard selection.

For analytical crib-table work, distinguish exact deterministic enumeration
inside a stated model from a closed-form global optimum. Iterative best response
is deterministic and can converge to a stable policy for the modeled table, but
it is still an iterative policy process. If dampening is used, keep measured
sample statistics (`n`, `mu`, `se`) separate from policy-transition values
(`policy_mu`, `policy_se`). Reports and summaries should use measured
statistics; policy selection and convergence checks may use dampened policy
values when that is the policy that will actually drive the next generation.

Convergence checks must not ignore missing conditional buckets. If a generated
table is expected to compare every discard pair, player role, and starter rank,
missing measured cut-rank data should prevent a finite convergence claim rather
than silently counting as zero shift.

Historical crib tables should be named with enough attribution and methodology
context to avoid overstating provenance. If a table is believed to be
Colvert/Bowman, Rasmussen, Schell, Hessel, or another source, document the
source and uncertainty instead of implying stronger provenance than the project
has verified.

Near the end of this section, observe these boundaries: do not summarize
Monte Carlo output without the sample counts needed to compute the displayed
uncertainty. Do not claim exact agreement with external tables when the
generation methodology differs.

The pipeline emits two artifacts. `generate_table.py` writes the full table plus
a lean client artifact (`build_client_table`, the `--client-output`
`expected_crib_points.client.json`) that the `cribbage-trainer` web app consumes
directly. The client artifact keeps only what the browser reads: per-bucket `mu`
and per-category point `mu`, plus `starter_suit_relation` only for suited or
Jack discards. It is published to the rolling `expected-crib-points` release.
Keep the two repos in sync: bucket-schema changes must be reflected in both
`build_client_table` here and the trainer's lookup.

Crib EV depends on the starter's suit only through flushes (possible only for a
suited discard) and his-nobs (a discarded Jack matching the starter suit). For
every other discard the `starter_suit_relation` buckets are sampling noise, so
the lean client artifact omits them for unsuited, non-Jack discards. Do not add
suit conditioning where the rules make it impossible.

The weekly production generation runs close to the 6-hour GitHub Actions cap
(about 20 minutes of headroom) with a razor-thin convergence margin (max EV
shift near the 0.10 threshold). Do not trim the sample count to buy wall-clock
time: fewer samples raise the shift and risk a non-convergence failure. Prefer
resume-across-runs (the resumable-checkpoint design above) if the cap becomes a
recurring problem.

The expected-play pipeline is separate from the expected-crib pipeline.
`generate_play_table.py` uses the analytical `E(h +/- c)` solution as its
initial discard policy, trains a rank-only hidden-information pegging policy by
rollout iterative best response, and refines discards using
`E(h +/- c +/- deltaP)`. Its full artifact stores paired uncertainty for the
keyed player's delta plus absolute Pone and Dealer point-type totals. Its lean
client artifact recursively strips `n` and `se` while retaining those means.
Do not expose hidden opponent cards to policy inputs or move rollout decisions
into the browser.

Seeded play-table samples are independent by canonical hand, role, and
cumulative sample index. Preserve this property when changing generation or
checkpoint behavior so resumed runs remain equivalent to uninterrupted runs.
The Cribbage Pro comparison runs on every production generation, offline,
against a small, attributed sample of their published (empirical human-play)
pegging values vendored in `artifact_pipeline/cribbage_pro_reference.py`
(re-expressed in this project's keys, with a no-copyright-claim note like the
historical crib tables). It records regression metrics in the artifact metadata
and gates the build: `--fail-on-regression` fails generation when the
role-relative deltas diverge grossly from the reference (sign flip,
scaling/offset bug). Keep a small representative sample rather than the full
table, and do not add a live network fetch back into the pipeline.

Runtime was measured end to end on the current code, single-threaded on an
Apple M2 laptop. Fixed setup -- the analytical seed, rollout
best-response training, and the per-outer policy tables -- is about 16 minutes,
and the final sampling phase adds about 0.47 seconds per `--samples` step across
all 3,640 seat entries (roughly 7,750 pegging simulations per second). So
`T_local ~= 16 min + 0.47 s * samples`. The GitHub-hosted runner measured about
1.6x slower than that laptop, consistent across both an exact analytical test
shard and the sampling-heavy fast suite (each isolated from checkout and
install), so multiply the local figure by ~1.6 for the real run and by ~2.5 for
a paranoid bound. The CI figures below are the operative ones; the local number
is only the measurement source behind that multiplier.

The scheduled workflow runs a deliberately time-capped single pass
(`--ibr-samples=30000`, `--samples=13000`, two outer and two IBR iterations, no
`--target-standard-error`, no `--max-samples`, no `--fail-on-non-convergence`,
and `--no-resume`). At `--samples=13000` the local run is about 118 minutes,
i.e. about 3.1 hours on the CI runner and about 4.9 hours at the paranoid 2.5x
-- inside the six-hour cap and the job's 330-minute `timeout-minutes`. The
per-entry standard error is about 2.7 / sqrt(samples), near 0.024. The emitted
artifact records `joint_policy_converged: false`; that is expected for the
capped run and is not a failure.

Each sampling pass (the per-outer policy tables and the final pass) emits a
progress heartbeat to stderr -- a start line plus `hand X/Y` lines at every
checkpoint with elapsed, remaining, and median standard error -- so a long run
is observable rather than silent. The rollout-IBR training phases stay quiet.

Raising `--samples` tightens the SE (and `--ibr-samples` improves policy quality
at a fixed setup cost): about 16,000 samples still finishes under the cap at the
paranoid 2.5x. Beyond that -- for example a tight `--target-standard-error=0.02`
goal, near 18,000 samples, which fits at the measured speed but approaches the
cap if a runner is much slower -- adopt the resume-across-runs checkpoint design
above rather than risk a single-job timeout. Do not silently cut samples below
the configured value to buy wall-clock time.

## Lint Configuration Expectations

Do not assume lint rules are enforced unless they are present in local
configuration or pre-commit output. The artifact pipeline is covered by local
pre-commit and CI checks for both `pylint --persistent=n artifact_pipeline` and
`flake8 artifact_pipeline`. The current pylint configuration does not enforce
magic-number checks or unusually strict short-variable-name checks. Use
`npm run spellcheck` to catch misspellings and many opaque identifier fragments
that pylint accepts as valid snake_case.

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

When an app or connector reports expired GitHub authentication, do not assume
all GitHub access is unavailable. First run `gh auth status` to check whether
the GitHub CLI still has a valid keyring token. If it does, use `gh pr view`
for pull request status and `gh api graphql` for review-thread state before
asking the human maintainer to reauthenticate the connector. If CLI
authentication also fails, ask the maintainer to run `gh auth login` or
`gh auth refresh` before continuing GitHub work.

If GitHub review comments exist, inspect their current thread status and address
unresolved comments before requesting review again. Reply clearly when an agent
implemented a change on behalf of a human.

Before resolving a pull request review thread, add a reply that explains why
the thread is considered resolved. Reference the code, documentation, test, or
reasoned no-change decision that addresses the feedback, and identify the agent
or human who made that assessment.

After review comments exist, avoid force-pushing a pull request branch because it
can destabilize GitHub review anchors and make human review harder. Use additive
commits unless a human maintainer explicitly asks for history rewriting.

When an AI agent posts or edits pull request prose, comments, summaries, or
resolution notes that a human maintainer has not reviewed, attribute the prose
to the agent alone, for example "OpenAI Codex". Do not use ambiguous shared
attribution such as "OpenAI Codex / me" unless the human maintainer explicitly
approved that wording. Prefer natural Markdown paragraphs for GitHub-rendered
PR prose; do not hard-wrap prose in PR descriptions or comments when GitHub's
renderer will wrap it for the viewer.

Near the end of this section, observe these boundaries: do not claim an issue is
complete until requested files are updated, required constraints are represented
in documentation, and the diff has been reviewed against the issue text. Do not
resolve review feedback without either making the requested change or explaining
why no change is appropriate.
