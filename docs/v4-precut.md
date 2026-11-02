# Version-4 pre-cut twin report and guard

Issue #135's [November 2 decisions](https://github.com/markafitzgerald1/simulate-cribbage-games/issues/135#issuecomment-6591347660)
approve all 156 distinct-rank/role comparisons, including 24 labelled Jack
rows. The producer reports each completed v4 generation in
`__metadata__.precut_twin_report`. Same-rank groups have no suited twin.
Focused runs report their selected twins with the same 156-row family size.
The lean client retains its existing shape.

`artifact_pipeline.crib_precut.precut_twin_report(state)` takes the decoded,
validated v4 state. It uses the authoritative integer joint moments, never
rounded or displayed means. For cut rank c its physical-starter weight is
`(4 - own_discard.count(c))/50`. The shared base cancels; the residual and
suit streams contribute independent variances. Within each stream all
cross-cut and cross-variant covariance is retained. Gap, residual, flush and
nobs each carry N, mean and SE. Missing observations and N=1 have unavailable
bounds; a measured zero SE does not establish absence of rare events.

The report supplies pointwise two-sided 95% normal bounds and Bonferroni
bounds using `Phi^-1(1 - 0.05/(2*156))` (about 3.598). These are fixed-policy,
fixed-comparison diagnostic approximations. They do not establish calibrated
coverage, learned-policy uncertainty or a crib-wide noise floor.

With `--estimator-v4`, `--precut-guard=report` is the default behavior.
`--precut-guard=enforce` rejects a completed generation only if at least one
simultaneous upper bound is strictly below zero. It names each failed
rank group and role. Unresolved rows are reported and do not fail. There is
no tolerance, sign clamp, per-cut sign gate or sampling-until-positive.
The flag is rejected outside v4 mode. It does not change sampling identity;
resuming with enforcement recomputes the report from moments, ignoring any
saved derived report. Completed generations are checked before writing their
full/client outputs and before policy transition or successful return.

The [survey](https://github.com/markafitzgerald1/simulate-cribbage-games/issues/135#issuecomment-6570652620)
measured 156 positive rows at N=22,000 under one frozen historical policy.
Its minimum observed gap/SE was 10.30, so all 156 also clear zero with the
simultaneous normal bounds. That evidence is conditional on that policy;
the producer checks each new completed generation because policies can change.
The residuals are second-order for Mark's accepted decision, with no further
mechanism study required here. The v2 sidecar remains required before v4
activation; this report does not publish consumer uncertainty.
