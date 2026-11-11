//! The Rust pegging rules against the published Python engine.
//!
//! `artifact_pipeline/pegging_golden.py` plays a fixed sample of deals with
//! the Python engine under a deterministic choice rule and writes each deal's
//! final points to `pegging_golden.txt`. This test replays the same deals with
//! `State` under the same rule, so any scoring difference between the two
//! independent implementations fails here.

use cfr_inputs::game::{State, canonical, feasible};

/// Legal rank number (count + cards held) modulo the legal ranks, or a go:
/// the rule `pegging_golden.RotatingRule` applies in Python.
fn rotating_choice(state: &State) -> Option<u8> {
    let legal = state.legal();
    if legal.is_empty() {
        return None;
    }
    let count = usize::try_from(state.count).expect("count fits");
    Some(legal[(count + state.cards_left[state.next]) % legal.len()])
}

#[test]
fn rust_rules_match_the_python_engine_on_every_golden_deal() {
    let hands = canonical();
    let mut deals = 0;
    for line in include_str!("pegging_golden.txt").lines() {
        let fields: Vec<i64> = line
            .split(' ')
            .map(|field| field.parse().expect("number"))
            .collect();
        let [pone_index, dealer_index, pone_points, dealer_points] = fields[..] else {
            panic!("malformed golden line: {line}");
        };
        let pone = hands[usize::try_from(pone_index).expect("index")];
        let dealer = hands[usize::try_from(dealer_index).expect("index")];
        assert!(feasible(&pone, &dealer), "infeasible deal: {line}");
        let mut state = State::new(pone, dealer);
        while !state.play(rotating_choice(&state)) {}
        let points = [i64::from(state.points[0]), i64::from(state.points[1])];
        assert_eq!(points, [pone_points, dealer_points], "deal {line}");
        deals += 1;
    }
    assert!(deals > 5000, "only {deals} golden deals");
}
