# CLAUDE.md

@AGENTS.md

This file is intentionally a thin wrapper, and agent conventions are tiered.
`AGENTS.md` — imported above, so it is resident in every session — is the
shared repository contract, written to be read by Google Jules, OpenAI Codex,
Anthropic Claude and any other agent. `skills/SKILLS.md` holds the default
validation and governance checklist and is read before complex work.

Add new durable learnings to whichever tier matches: `AGENTS.md` for anything
true of the repository regardless of which tool is working on it, and
`skills/SKILLS.md` for validation procedure. What belongs here instead is the
narrow set that is true of Claude Code alone — its harness, its worktrees,
this machine's shell — because no other harness reads this file, and the
shared contract should not carry guidance only one tool can use.

## Claude-specific notes

- **Match the model to the subtask when delegating.** Prefer doing small,
  well-specified changes directly: a subagent that has to re-derive the
  session's context usually costs more than it saves. When a piece genuinely
  is mechanical and fully specified — mirroring a reviewed edit into a second
  file, drafting tests against a settled interface — pass `model: sonnet`
  rather than inheriting the parent model. Reserve the heavier model for the
  judgement calls: which design survives a failure mode, how to word a
  residual-risk paragraph, whether a measurement actually supports its claim.
  This is written down because it was a real observed gap, not a
  hypothetical: a long session ran entirely on the heavy model for work that
  did not need it, and only noticed when asked.
- A `.claude/worktrees/<name>` checkout needs no Python environment setup.
  The pyenv interpreter already on `PATH` there carries every dependency in
  `requirements.txt`, so `pre-commit`, the pre-push gates and the validation
  set all run from a fresh worktree as they do from the main checkout.
  Prepending the main checkout's `env/` virtualenv to `PATH` is unnecessary.
- `numpy` is not a dependency of this project and is absent from that
  interpreter. A failed `import numpy` is therefore evidence of nothing, and
  is not a reason to go looking for a "real" interpreter — check
  `requirements.txt` before concluding an environment is incomplete.
- Workflow runs can take a couple of minutes to appear after `gh pr create`.
  During that window `gh run list --branch`, the commit's `check-runs`, and
  `actions/runs?head_sha=` all report zero, which reads exactly like
  workflows failing to trigger. Poll for several minutes before diagnosing
  anything from their absence.
