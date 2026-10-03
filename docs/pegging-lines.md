# Typical first-exchange pegging lines: proposed contract

Design for issue #176. This document is provisional; no generator changes or
release assets accompany this initial draft. The dealer conditioning question
below must be settled before implementation.

## Dealer conditioning question

Proposed interpretation: for each opponent opening lead, select the dealer's
most frequent observed response among simulations with that lead. Its frequency
uses that lead's simulation count as the denominator. E(deltaP) uses **all**
simulations with that opponent lead, including less frequent dealer responses.
It is not E(deltaP) conditional on both the lead and the selected response.
The issue does not explicitly resolve this distinction. Confirm this
interpretation before implementing it.

## Artifact and populations

Write a separate minified `expected_play_points.lines.json` with schema
`expected-play-lines.v1`, `means_sha256`, `provenance`, `qualifications`, and
`entries`. Entry identities use the existing canonical four-rank keys and
`Pone`/`Dealer` roles: 1,820 keys times two roles for a complete run.

Each role entry contains its total simulation count `n` and a `leads` object
keyed by opening rank (`A23456789TJQK`). Each available lead record contains:

- `n`: simulations with that opening lead.
- `frequency`: lead count divided by the role entry's total count.
- `frequency_se`: plug-in binomial SE, sqrt(p * (1 - p) / total count).
- `delta`: `n`, `mu`, and `se` for the keyed player's complete-hand pegging
  points minus the opponent's, conditional on that opening lead.

For Pone, these are the keyed hand's policy-selected opening leads. For Dealer,
these are the sampled opponent's opening leads; each lead additionally has a
`response` object with the modal response `rank`, its observed `n`,
`frequency`, and `frequency_se`. Response frequency divides by the lead count;
response SE uses that same denominator. Break count ties by rank order and
document that a tie is not evidence of a uniquely preferred move.

Require at least two observations to emit a conditional mean and its SE.
Omit under-sampled lead records, and omit an under-sampled modal response.
Keep the role's total count unchanged: frequencies need not sum to one when
records are unavailable. Missing entries, leads, responses, files, and rejected
digest pairings mean unavailable, never zero. Measured zero remains available.
These thresholds only make sample SE computable; they do not establish precision.

## Production and pairing

Observe the first two actual policy selections during the final measurement
pass that already produces the play means. Accumulate the complete-hand delta
returned by that same simulation into its opening-lead bucket. Do not replay
the game, force a lead, reselect a response, consume extra random draws, retrain,
or export the training action estimates. Preserve mixture and fallback behavior,
including hands with only one legal rank. Policy inputs remain hidden-information.

Save sufficient counts and conditional moments in full-table checkpoints to
resume without losing attribution. Reject old or incompatible checkpoints that
lack those statistics rather than treating their previous samples as zero.
Seeded resumed results must match uninterrupted sampling.

Write the client means first and hash their exact on-disk bytes with SHA-256.
Write the lines artifact from that run's final accumulators, carrying the final
policy fingerprint, seed, generation method, and `joint_policy_converged`.
The reader must reject a different means digest, including whitespace changes.
The artifact's qualifications explicitly describe the frozen policy, its
non-converged status when applicable, observed conditional outcomes rather than
alternative-action values, and exclusion of policy-learning uncertainty.

Wire upload/download and the existing rolling release's single publication
call to carry the new artifact alongside the play means and uncertainty.
Bounded pull-request generation exercises this path. Do not dispatch production
generation or replace existing release assets during this PR.

## Size estimate and exclusions

A synthetic full-width JSON fixture uses all 1,820 keys, every distinct own rank
as a Pone lead (5,915 records), all 13 opponent lead ranks as Dealer (23,660
records), one response per Dealer lead, and long full-precision numeric values.
With the proposed named fields it occupies 7,099,498 bytes minified, including
one trailing newline. This is a conservative design estimate, not a generated
policy measurement or a transfer/memory budget guarantee. Compression of
repeated fixture values would misleadingly understate real transfer cost.

The trainer's current source gate warns above 250 changed lines and fails above
400; JSON artifacts count in full. A new minified one-line file contributes one
added line, and replacement contributes one addition plus one deletion. Byte
size remains a separate consumer concern. No production artifact is vendored in
this simulator PR. Measure bounded output and the complete synthetic shape
again after implementation, without regenerating the published release.

Exclude later exchanges, full traces, hidden opponent hands, suit conditioning,
board-position strategy, per-response conditional means, alternative-action
comparisons, action optimality claims, confidence thresholds, browser simulation,
trainer loading/display changes, and modifications to existing client means or
the uncertainty sidecar contract.

Tests must exercise actual generator integration, role-relative delta signs,
count denominators, conditional means, measured zero versus absence, seeded
resume, unchanged client means, and digest rejection. In scratch copies, prove
tests fail when frequency denominators or conditional-mean attribution are
mutated, and when digest verification is disabled or hashes the wrong bytes.
