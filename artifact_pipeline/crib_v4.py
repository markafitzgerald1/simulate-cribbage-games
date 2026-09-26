"""Explicitly opt-in v4 crib generation with resumable joint moments.

The scheduled generator remains on its existing v3 path. This module is entered
only by ``generate_table.py --estimator-v4`` and uses its frozen selector/scorer
callbacks without importing the legacy simulator on its own.
"""

import hashlib
import json
import os
import platform
import random
import secrets
import signal
from functools import lru_cache
from fractions import Fraction

from artifact_pipeline.crib_decomposition import (
    RANK_CATEGORIES,
    ROOT,
    SUIT_CATEGORIES,
    CribGroup,
    base_observation,
    bucket_populations,
    residual_observation,
    sample_hand,
    suit_observation,
)
from artifact_pipeline.crib_v4_state import (
    CENTER_DENOMINATOR,
    SCALE,
    STREAM_ALLOCATION,
    active_streams,
    add_row,
    coordinate_labels,
    decode_moments,
    empty_moments,
    encode_moments,
    integer_row,
    observation_coordinates,
    projected_statistics,
)

GENERATION_METHOD = "artifact_pipeline.generate_table.v4"
ESTIMATOR_CONTRACT = "shared-rank-relation-v1"
CENTERING_CONTRACT = "uniform-two-card-rank-completion-v1"
SAMPLE_UNIT = "independent-vector-rows-per-active-stream"
SELECTOR_CONTRACT = "legacy-suit-sensitive-first-max-v1"
RNG_CONTRACT = "python-random-sample-v1"
DECK_ORDER = "rank-index-then-suit-index-v1"
ROLES = ("Dealer", "Pone")
PHASES = ("sampling", "complete", "transition_pending")
METADATA_FIELDS = {
    "generation_method",
    "estimator_contract",
    "relation_centering_contract",
    "sample_unit",
    "selector_contract",
    "rng_contract",
    "deck_order",
    "python_implementation",
    "python_version",
    "scale",
    "seed",
    "seed_was_specified",
    "randomness_key",
    "requested_pairs",
    "stream_allocation",
    "run_control",
    "bootstrap_sha256",
    "generation",
    "phase",
    "generation_accumulators",
    "policy_sha256",
    "use_control_variates",
    "estimator_state",
}


def _canonical_json(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _digest(value):
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _policy_hash(policy_payload):
    return _digest(
        "legacy-static-policy-v1" if policy_payload is None else policy_payload
    )


def _requested_pairs(requested, legacy):
    canonical = legacy.get_canonical_pairs()
    selected = list(requested) if requested is not None else canonical
    if not selected or len(set(selected)) != len(selected):
        raise ValueError("v4 requires a nonempty unique canonical pair selection")
    if any(pair not in canonical for pair in selected):
        raise ValueError("v4 pair selection contains an unknown key")
    normalized = [pair for pair in canonical if pair in selected]
    for pair in normalized:
        rank_key = pair.rsplit("_", 1)[0]
        twin = f"{rank_key}_{'Unsuited' if pair.endswith('Suited') else 'Suited'}"
        if pair.endswith("_Suited") and twin not in selected:
            raise ValueError("v4 distinct-rank groups require complete twins")
        if (
            pair.endswith("_Unsuited")
            and rank_key.split("_")[0] != rank_key.split("_")[1]
        ):
            if twin not in selected:
                raise ValueError("v4 distinct-rank groups require complete twins")
    return normalized


def _rank_keys(pairs):
    return list(dict.fromkeys(pair.rsplit("_", 1)[0] for pair in pairs))


def _physical_group(rank_key, legacy):
    first, second = rank_key.split("_")
    first_index = legacy.Index.indices.index(first)
    second_index = legacy.Index.indices.index(second)
    unsuited = (legacy.Card(first_index, 0), legacy.Card(second_index, 1))
    suited = (
        (legacy.Card(first_index, 0), legacy.Card(second_index, 0))
        if first_index != second_index
        else None
    )
    return CribGroup(tuple(legacy.DECK_SET), unsuited, suited, 6)


@lru_cache(maxsize=None)
def _rank_points(ranks, scorer):
    cards = [scorer.Card(rank, 0) for rank in ranks[:4]]
    starter = scorer.Card(ranks[4], 1)
    points = scorer.score_hand_and_starter_breakdown(cards, starter, is_crib=True)
    return {kind: points[kind] for kind in RANK_CATEGORIES}


def _centers(group, legacy):
    own_ranks = (group.unsuited[0].index, group.unsuited[1].index)
    centers = {}
    for cut in range(len(legacy.Index.indices)):
        available = [4] * len(legacy.Index.indices)
        for rank in (*own_ranks, cut):
            available[rank] -= 1
        totals = {kind: 0 for kind in RANK_CATEGORIES}
        for first, first_count in enumerate(available):
            for second in range(first, len(available)):
                second_count = available[second]
                multiplicity = (
                    first_count * second_count
                    if first != second
                    else first_count * (first_count - 1) // 2
                )
                if not multiplicity:
                    continue
                points = _rank_points((*own_ranks, first, second, cut), legacy)
                for kind in RANK_CATEGORIES:
                    totals[kind] += multiplicity * points[kind]
        centers[cut] = {
            kind: Fraction(totals[kind], CENTER_DENOMINATOR) for kind in RANK_CATEGORIES
        }
    return centers


def _centering_numerators(centers, rank_names):
    return [
        str(int(centers[cut][kind] * CENTER_DENOMINATOR))
        for cut in range(len(rank_names))
        for kind in RANK_CATEGORIES
    ]


def _empty_group(group, legacy):
    names = legacy.Index.indices
    centers = _centers(group, legacy)
    return {
        "centering_denominator": CENTER_DENOMINATOR,
        "centering_numerators": _centering_numerators(centers, names),
        "streams": {
            name: empty_moments(coordinate_labels(group, names, name))
            for name in active_streams(group)
        },
    }


def _run_control(args):
    if args.infinite and args.samples is None:
        mode = "fixed_unbounded"
    elif (
        args.convergence_threshold is not None
        or (args.max_generations is not None and args.max_generations > 1)
        or args.infinite
    ):
        mode = "iterative"
    else:
        mode = "fixed_finite"
    return {
        "mode": mode,
        "target_samples": args.samples,
        "dampening": args.dampening,
        "convergence_threshold": args.convergence_threshold,
        "max_generations": args.max_generations,
        "fail_on_non_convergence": args.fail_on_non_convergence,
        "infinite": args.infinite,
    }


def _bootstrap_policy(args, legacy):
    if args.bootstrap is None:
        return None, None
    with open(args.bootstrap, "rb") as bootstrap_file:
        bootstrap_digest = hashlib.sha256(bootstrap_file.read()).hexdigest()
    accumulators, _metadata = legacy.load_output(args.bootstrap)
    return (
        legacy.serialize_accumulators(accumulators, include_nested=False),
        bootstrap_digest,
    )


def _contract_identity(args, pairs):
    return {
        "generation_method": GENERATION_METHOD,
        "estimator_contract": ESTIMATOR_CONTRACT,
        "relation_centering_contract": CENTERING_CONTRACT,
        "sample_unit": SAMPLE_UNIT,
        "selector_contract": SELECTOR_CONTRACT,
        "rng_contract": RNG_CONTRACT,
        "deck_order": DECK_ORDER,
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "scale": SCALE,
        "seed": args.seed,
        "seed_was_specified": args.seed is not None,
        "requested_pairs": pairs,
        "stream_allocation": STREAM_ALLOCATION,
        "use_control_variates": True,
    }


def _fresh_state(args, pairs, legacy):
    policy, bootstrap_digest = _bootstrap_policy(args, legacy)
    randomness = (
        ["seed", args.seed]
        if args.seed is not None
        else ["nonce", secrets.token_hex(32)]
    )
    state = {
        **_contract_identity(args, pairs),
        "randomness_key": randomness,
        "run_control": _run_control(args),
        "bootstrap_sha256": bootstrap_digest,
        "generation": 0,
        "phase": "sampling",
        "generation_accumulators": policy,
        "policy_sha256": _policy_hash(policy),
        "estimator_state": {},
    }
    for rank_key in _rank_keys(pairs):
        group = _physical_group(rank_key, legacy)
        state["estimator_state"][rank_key] = {
            role: _empty_group(group, legacy) for role in ROLES
        }
    return state


def _decode_group(payload, group, legacy):
    if set(payload) != {"centering_denominator", "centering_numerators", "streams"}:
        raise ValueError("Incomplete group state")
    expected = _centering_numerators(_centers(group, legacy), legacy.Index.indices)
    if (
        payload["centering_denominator"] != CENTER_DENOMINATOR
        or payload["centering_numerators"] != expected
        or list(payload["streams"]) != list(active_streams(group))
    ):
        raise ValueError("Group centering or stream allocation is incompatible")
    streams = {
        name: decode_moments(
            saved, coordinate_labels(group, legacy.Index.indices, name)
        )
        for name, saved in payload["streams"].items()
    }
    if len({stream["count"] for stream in streams.values()}) != 1:
        raise ValueError("A group has unequal active stream counts")
    return {
        "centering_denominator": CENTER_DENOMINATOR,
        "centering_numerators": expected,
        "streams": streams,
    }


def _validate_control(saved, current):
    if set(saved) != set(current) or saved["mode"] != current["mode"]:
        raise ValueError("v4 run mode is incompatible with the checkpoint")
    for name in current:
        if name == "target_samples" and saved["mode"] == "fixed_finite":
            if isinstance(saved[name], bool) or not isinstance(saved[name], int):
                raise ValueError("v4 saved target is invalid")
            if current[name] < saved[name]:
                raise ValueError("v4 fixed-policy target cannot decrease")
        elif _canonical_json(saved[name]) != _canonical_json(current[name]):
            raise ValueError(f"v4 run control changed: {name}")


def _check_metadata(saved, args, pairs, legacy):
    """Check the versioned experiment identity before decoding any moments."""
    expected = _contract_identity(args, pairs)
    if set(saved) != METADATA_FIELDS or any(
        _canonical_json(saved.get(key)) != _canonical_json(value)
        for key, value in expected.items()
    ):
        raise ValueError("v4 checkpoint contract or requested keys are incompatible")
    _validate_control(saved["run_control"], _run_control(args))
    if (
        not isinstance(saved["generation"], int)
        or isinstance(saved["generation"], bool)
        or saved["generation"] < 0
    ):
        raise ValueError("Invalid v4 generation phase")
    if saved["phase"] not in PHASES:
        raise ValueError("Invalid v4 generation phase")
    randomness = saved["randomness_key"]
    if saved["seed_was_specified"]:
        if _canonical_json(randomness) != _canonical_json(["seed", args.seed]):
            raise ValueError("v4 seeded randomness key changed")
    else:
        valid_shape = (
            isinstance(randomness, list)
            and len(randomness) == 2
            and randomness[0] == "nonce"
            and isinstance(randomness[1], str)
        )
        if not valid_shape or len(randomness[1]) != 64:
            raise ValueError("Invalid v4 unseeded nonce")
        if any(digit not in "0123456789abcdef" for digit in randomness[1]):
            raise ValueError("Invalid v4 unseeded nonce")
    if args.bootstrap is not None:
        with open(args.bootstrap, "rb") as bootstrap_file:
            digest = hashlib.sha256(bootstrap_file.read()).hexdigest()
        if saved["bootstrap_sha256"] != digest:
            raise ValueError("v4 bootstrap source changed")
    if _policy_hash(saved["generation_accumulators"]) != saved["policy_sha256"]:
        raise ValueError("v4 frozen policy hash is invalid")
    legacy.deserialize_accumulators(saved["generation_accumulators"])


def _decode_groups(saved, pairs, legacy):
    groups = saved["estimator_state"]
    if set(groups) != set(_rank_keys(pairs)):
        raise ValueError("v4 checkpoint groups are incomplete")
    decoded = {}
    for rank_key in _rank_keys(pairs):
        group = _physical_group(rank_key, legacy)
        if set(groups[rank_key]) != set(ROLES):
            raise ValueError("v4 checkpoint roles are incomplete")
        decoded[rank_key] = {
            role: _decode_group(groups[rank_key][role], group, legacy) for role in ROLES
        }
    return decoded


def _check_phase(state, decoded):
    """Check count/phase consistency before scheduling another row."""
    target = state["run_control"]["target_samples"]
    if target is not None:
        counts = [
            entry["streams"]["base"]["count"]
            for roles in decoded.values()
            for entry in roles.values()
        ]
        if any(count > target for count in counts):
            raise ValueError("v4 checkpoint exceeds its saved target")
        if state["phase"] != "sampling" and any(count != target for count in counts):
            raise ValueError("v4 completed phase has incomplete groups")
    if (
        state["phase"] == "transition_pending"
        and state["run_control"]["mode"] != "iterative"
    ):
        raise ValueError("Only iterative v4 runs can await transition")


def _load_state(args, pairs, legacy):
    with open(args.output, "r", encoding="utf-8") as table_file:
        table = json.load(table_file)
    saved = table.get(legacy.METADATA_KEY)
    if (
        not isinstance(saved, dict)
        or saved.get("generation_method") != GENERATION_METHOD
    ):
        raise ValueError("v4 cannot resume a legacy or client-only artifact")
    _check_metadata(saved, args, pairs, legacy)
    decoded = _decode_groups(saved, pairs, legacy)
    saved["estimator_state"] = decoded
    target = saved["run_control"]["target_samples"]
    _check_phase(saved, decoded)
    saved["run_control"] = _run_control(args)
    if (
        saved["phase"] == "complete"
        and target != saved["run_control"]["target_samples"]
    ):
        saved["phase"] = "sampling"
    return saved


def _policy_accumulators(state, legacy):
    return legacy.deserialize_accumulators(state["generation_accumulators"])


def _score_deal(legacy, role, policy):
    def score(own_discard, opponent_hand, starters):
        kept = legacy.select_opponent_kept_cards_dynamic(
            role, list(opponent_hand), policy
        )
        discarded = [card for card in opponent_hand if card not in kept]
        crib = [*own_discard, *discarded]
        return {
            starter: legacy.score_hand_and_starter_breakdown(
                crib, starter, is_crib=True
            )
            for starter in starters
        }

    return score


def _row_rng(state, rank_key, role, stream, index):
    identity = [
        ESTIMATOR_CONTRACT,
        state["randomness_key"],
        state["generation"],
        state["policy_sha256"],
        rank_key,
        role,
        stream,
        index,
    ]
    return random.Random(json.dumps(identity, ensure_ascii=True, separators=(",", ":")))


def _sample_round(state, identity, group, legacy, policy):
    rank_key, role = identity
    entry = state["estimator_state"][rank_key][role]
    streams = entry["streams"]
    centers = {
        cut: {
            kind: int(entry["centering_numerators"][cut * 3 + position])
            * Fraction(1, CENTER_DENOMINATOR)
            for position, kind in enumerate(RANK_CATEGORIES)
        }
        for cut in range(len(legacy.Index.indices))
    }
    score = _score_deal(legacy, role, policy)
    observations = {}
    for stream in active_streams(group):
        rng = _row_rng(state, rank_key, role, stream, streams["base"]["next_index"])
        hand = sample_hand(group, stream, rng)
        if stream == "base":
            observations[stream] = base_observation(group, hand, score)
        elif stream == "residual":
            observations[stream] = residual_observation(group, hand, score)
        else:
            observations[stream] = suit_observation(group, hand, score, centers)
    return {
        stream: integer_row(
            streams[stream]["labels"],
            observation_coordinates(observations[stream], legacy.Index.indices, stream),
        )
        for stream in active_streams(group)
    }


def _component_coefficients(rank_name, variant, relation_name, kind):
    coefficients = {"base": {}}
    if kind in RANK_CATEGORIES:
        coefficients["base"][f"{rank_name}/base/{kind}"] = 1
        if variant == "Suited":
            coefficients["residual"] = {f"{rank_name}/residual/{kind}": 1}
        if relation_name != ROOT:
            coefficients["suit"] = {
                f"{rank_name}/{variant}/{relation_name}/correction_{kind}": 1
            }
    else:
        coefficients["suit"] = {f"{rank_name}/{variant}/{relation_name}/{kind}": 1}
    return coefficients


def _bucket_statistics(streams, rank_name, variant, relation_name):
    points = {}
    coefficients = {}
    for kind in (*RANK_CATEGORIES, *SUIT_CATEGORIES):
        terms = _component_coefficients(rank_name, variant, relation_name, kind)
        points[kind] = projected_statistics(streams, terms)
        for stream, weights in terms.items():
            combined = coefficients.setdefault(stream, {})
            for label, weight in weights.items():
                combined[label] = combined.get(label, 0) + weight
    total = projected_statistics(streams, coefficients)
    if total is None:
        return None
    points["total"] = total.copy()
    return {**total, "points": points}


def _cut_output(group, streams, variant, legacy):
    output = {}
    legal = bucket_populations(group, variant)
    for cut, rank_name in enumerate(legacy.Index.indices):
        bucket = _bucket_statistics(streams, rank_name, variant, ROOT)
        if bucket is None:
            continue
        relations = {}
        for relation_name in (
            "matching_discard_suit",
            "matching_rank_1_suit",
            "matching_rank_2_suit",
            "non_matching_discard_suit",
        ):
            if (cut, relation_name) in legal:
                relations[relation_name] = _bucket_statistics(
                    streams, rank_name, variant, relation_name
                )
        bucket["starter_suit_relation"] = relations
        output[rank_name] = bucket
    return output


def _project_output(state, legacy):
    output = {legacy.METADATA_KEY: _encode_state(state)}
    for pair in state["requested_pairs"]:
        rank_key, variant = pair.rsplit("_", 1)
        group = _physical_group(rank_key, legacy)
        output[pair] = {
            role: _cut_output(
                group,
                state["estimator_state"][rank_key][role]["streams"],
                variant,
                legacy,
            )
            for role in ROLES
        }
    return output


def _encode_state(state):
    metadata = {key: value for key, value in state.items() if key != "estimator_state"}
    metadata["estimator_state"] = {
        rank_key: {
            role: {
                "centering_denominator": entry["centering_denominator"],
                "centering_numerators": entry["centering_numerators"],
                "streams": {
                    name: encode_moments(moments)
                    for name, moments in entry["streams"].items()
                },
            }
            for role, entry in roles.items()
        }
        for rank_key, roles in state["estimator_state"].items()
    }
    return metadata


def _write_checkpoint(state, args, legacy):
    output = _project_output(state, legacy)
    temporary = f"{args.output}.tmp"
    with open(temporary, "w", encoding="utf-8") as table_file:
        json.dump(output, table_file, indent=2, allow_nan=False)
        table_file.write("\n")
    os.replace(temporary, args.output)
    if not args.no_client_output:
        client_path = args.client_output or legacy.derive_client_output_path(
            args.output
        )
        legacy.write_client_output(output, client_path)
    return output


def _measured_accumulators(state, legacy):
    output = _project_output(state, legacy)
    measured = {}
    for pair in state["requested_pairs"]:
        measured[pair] = {}
        for role in ROLES:
            measured[pair][role] = {
                cut: legacy.statistics_to_accumulator(bucket)
                for cut, bucket in output[pair][role].items()
            }
    return measured


def _prepare_transition(state, legacy):
    previous = _policy_accumulators(state, legacy)
    measured = _measured_accumulators(state, legacy)
    next_policy = legacy.build_generation_accumulators(
        previous, measured, state["requested_pairs"], state["run_control"]["dampening"]
    )
    return previous, measured, next_policy


def _should_stop_after_complete(state, legacy):
    control = state["run_control"]
    if control["mode"] != "iterative":
        return True
    previous, measured, next_policy = _prepare_transition(state, legacy)
    if control["convergence_threshold"] is not None and state["generation"] > 0:
        shift = legacy.calculate_max_ev_shift(
            previous, next_policy, state["requested_pairs"], measured
        )
        if shift <= control["convergence_threshold"]:
            return True
    limit = control["max_generations"]
    if limit is not None and state["generation"] + 1 >= limit:
        if control["fail_on_non_convergence"]:
            raise RuntimeError("v4 generation limit reached before convergence")
        return True
    return False


def _transition(state, legacy):
    _previous, _measured, next_policy = _prepare_transition(state, legacy)
    payload = legacy.serialize_accumulators(next_policy, include_nested=False)
    state["generation"] += 1
    state["generation_accumulators"] = payload
    state["policy_sha256"] = _policy_hash(payload)
    state["estimator_state"] = {
        rank_key: {
            role: _empty_group(_physical_group(rank_key, legacy), legacy)
            for role in ROLES
        }
        for rank_key in _rank_keys(state["requested_pairs"])
    }
    state["phase"] = "sampling"


class _V4Run:
    """Keep interrupt and checkpoint transitions local to one opt-in run."""

    def __init__(self, args, requested, legacy):
        if args.samples is not None and args.samples < 2:
            raise ValueError("v4 finite targets require at least two rows per stream")
        self.args = args
        self.legacy = legacy
        self.pairs = _requested_pairs(requested, legacy)
        self.pending_stop = False
        if os.path.exists(args.output) and not args.no_resume:
            self.state = _load_state(args, self.pairs, legacy)
        else:
            self.state = _fresh_state(args, self.pairs, legacy)
            self.checkpoint()

    def checkpoint(self):
        return _write_checkpoint(self.state, self.args, self.legacy)

    def request_stop(self, _signal_number, _frame):
        self.pending_stop = True

    def sample_group(self, rank_key, role, policy):
        group = _physical_group(rank_key, self.legacy)
        entry = self.state["estimator_state"][rank_key][role]
        count = entry["streams"]["base"]["count"]
        starting_count = count
        limit = count + self.args.checkpoint_frequency
        target = self.state["run_control"]["target_samples"]
        if target is not None:
            limit = min(limit, target)
        while count < limit:
            rows = _sample_round(
                self.state, (rank_key, role), group, self.legacy, policy
            )
            for stream in active_streams(group):
                add_row(entry["streams"][stream], rows[stream])
            count += 1
            if self.pending_stop:
                break
        if count != entry["streams"]["base"]["count"]:
            raise ValueError("v4 stream rounds are inconsistent")
        if count > starting_count:
            self.checkpoint()
        if self.pending_stop:
            raise SystemExit(130)

    def sample_pass(self):
        policy = _policy_accumulators(self.state, self.legacy)
        for rank_key in _rank_keys(self.pairs):
            for role in ROLES:
                self.sample_group(rank_key, role, policy)
        target = self.state["run_control"]["target_samples"]
        if target is not None and all(
            entry["streams"]["base"]["count"] >= target
            for roles in self.state["estimator_state"].values()
            for entry in roles.values()
        ):
            self.state["phase"] = "complete"
            self.checkpoint()

    def execute(self):
        while True:
            if self.pending_stop:
                raise SystemExit(130)
            if self.state["phase"] == "complete":
                if _should_stop_after_complete(self.state, self.legacy):
                    return _project_output(self.state, self.legacy)
                self.state["phase"] = "transition_pending"
                self.checkpoint()
            if self.state["phase"] == "transition_pending":
                if self.pending_stop:
                    raise SystemExit(130)
                _transition(self.state, self.legacy)
                self.checkpoint()
            self.sample_pass()


def run(args, requested, legacy):
    """Run isolated v4; the legacy generator remains the default path."""
    current = _V4Run(args, requested, legacy)
    previous_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, current.request_stop)
    try:
        return current.execute()
    finally:
        signal.signal(signal.SIGINT, previous_handler)
