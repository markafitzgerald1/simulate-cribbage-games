//! Regenerates the six-layer CFR pegging inputs that the play-table
//! measurement pins (#203): optional-decision menus, per-Pone-hand game trees,
//! action offsets, the CFR+ mixture policy and its support bits.
//!
//! Each module mirrors one part of the research C++ in
//! `cribbage-research-2026-10/artifacts/regenerated-inputs/reproduction/`, with
//! the same operation order and no fused multiply-add, so its outputs can be
//! compared byte for byte with the saved research digests.

pub mod game;
