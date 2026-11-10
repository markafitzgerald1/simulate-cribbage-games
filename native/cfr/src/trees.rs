//! Loaded menus and per-Pone-hand game trees, mirroring `load`, `lookup`,
//! `Tree::build`, `Tree::save`, `Tree::read` and `make_tree` in the research
//! `stream.cpp`.
//!
//! Tree file `p` holds every feasible deal with Pone hand `p`, as little-endian
//! `u32` words: node count `n`, edge count `e`, 1,820 root ids (one per Dealer
//! hand, `u32::MAX` when infeasible), `n` nodes of (global menu index, first
//! edge), then `e` edges. A child id with the high bit set is a terminal; its
//! low byte is the signed Pone-minus-Dealer pegging margin after both players
//! finish with the heuristic.

use super::game::{Cards, State, feasible};
use super::menus::{FILES, NIL, RECORD};
use std::io;
use std::path::Path;

/// Terminal marker in a child id.
pub const TAG: u32 = 1 << 31;

/// Every menu record across the 3,640 files, in file order, with parents
/// rebased to global indices and action offsets assigned.
pub struct Menus {
    pub history: Vec<u64>,
    pub parent: Vec<u32>,
    pub offset: Vec<u32>,
    pub stage: Vec<u8>,
    pub width: Vec<u8>,
    pub parent_action: Vec<u8>,
    /// `starts[k]..starts[k + 1]` is file `k`'s range of global indices.
    pub starts: Vec<u32>,
    /// Total action slots; also `offset` one past the last menu.
    pub actions: u64,
}

impl Menus {
    pub fn len(&self) -> usize {
        self.history.len()
    }

    pub fn is_empty(&self) -> bool {
        self.history.is_empty()
    }

    /// Parse menu files from their bytes, in file order.
    pub fn from_files<B: AsRef<[u8]>>(files: &[B]) -> Menus {
        let total: usize = files.iter().map(|f| f.as_ref().len() / RECORD).sum();
        let mut m = Menus {
            history: Vec::with_capacity(total),
            parent: Vec::with_capacity(total),
            offset: Vec::with_capacity(total),
            stage: Vec::with_capacity(total),
            width: Vec::with_capacity(total),
            parent_action: Vec::with_capacity(total),
            starts: Vec::with_capacity(files.len() + 1),
            actions: 0,
        };
        for file in files {
            let bytes = file.as_ref();
            assert_eq!(bytes.len() % RECORD, 0, "Menus truncated");
            let start = u32::try_from(m.history.len()).expect("menu count");
            m.starts.push(start);
            for r in bytes.as_chunks::<RECORD>().0 {
                let parent = u32::from_le_bytes(r[8..12].try_into().unwrap());
                m.history
                    .push(u64::from_le_bytes(r[0..8].try_into().unwrap()));
                m.parent
                    .push(if parent == NIL { NIL } else { parent + start });
                m.offset
                    .push(u32::try_from(m.actions).expect("action offset"));
                m.stage.push(r[20]);
                m.width.push(r[21]);
                m.parent_action.push(r[23]);
                m.actions += u64::from(r[21]);
            }
        }
        m.starts
            .push(u32::try_from(m.history.len()).expect("menu count"));
        m
    }

    /// Read all menu files from `dir/menus/{k}.bin`.
    pub fn load(dir: &Path) -> io::Result<Menus> {
        let files = (0..FILES)
            .map(|k| std::fs::read(dir.join("menus").join(format!("{k}.bin"))))
            .collect::<io::Result<Vec<_>>>()?;
        Ok(Menus::from_files(&files))
    }

    /// Global menu index for the player to act in `s`.
    fn lookup(&self, s: &State, p: usize, d: usize) -> u32 {
        let k = s.next * 1820 + if s.next == 1 { d } else { p };
        let (begin, end) = (self.starts[k] as usize, self.starts[k + 1] as usize);
        let key = s.history_key();
        let range = &self.history[begin..end];
        let at = range.partition_point(|&h| h < key);
        assert!(at < range.len() && range[at] == key, "Missing info");
        u32::try_from(begin + at).expect("menu count")
    }
}

/// A decision node: its menu, its first edge, its menu's first action slot,
/// the seat to act (0 Pone, 1 Dealer) and the number of legal actions.
pub struct Node {
    pub info: usize,
    pub first: usize,
    pub off: usize,
    pub actor: u8,
    pub width: usize,
}

/// The game trees for one Pone hand.
pub struct Tree {
    pub roots: Vec<u32>,
    /// (global menu index, first edge) pairs, flattened.
    pub nodes: Vec<u32>,
    pub edges: Vec<u32>,
}

/// Signed terminal margin stored in a tagged child id.
pub fn leaf(id: u32) -> i32 {
    i32::from(id.to_le_bytes()[0].cast_signed())
}

impl Tree {
    /// Decision node `id`, read against its menu.
    pub fn node(&self, m: &Menus, id: u32) -> Node {
        let at = 2 * id as usize;
        let info = self.nodes[at] as usize;
        Node {
            info,
            first: self.nodes[at + 1] as usize,
            off: m.offset[info] as usize,
            actor: m.stage[info] % 2,
            width: usize::from(m.width[info]),
        }
    }

    fn grow(&mut self, menus: &Menus, mut s: State, p: usize, d: usize) -> u32 {
        loop {
            if s.n[0] <= 1 && s.n[1] <= 1 {
                s.finish();
                let v = s.points[0] - s.points[1];
                assert!((-127..=127).contains(&v), "Leaf bound");
                return TAG | u32::from(i8::try_from(v).expect("Leaf bound").cast_unsigned());
            }
            let legal = s.legal();
            if legal.len() < 2 || 4 - s.n[s.next] >= 3 {
                let action = s.heuristic();
                s.play(action);
                continue;
            }
            let info = menus.lookup(&s, p, d);
            let id = u32::try_from(self.nodes.len() / 2).expect("node count");
            let first = self.edges.len();
            self.nodes
                .extend_from_slice(&[info, u32::try_from(first).expect("edge count")]);
            self.edges.resize(first + legal.len(), 0);
            for (i, &r) in legal.iter().enumerate() {
                let mut next = s.clone();
                next.play(Some(r));
                self.edges[first + i] = self.grow(menus, next, p, d);
            }
            return id;
        }
    }

    /// Build the trees for Pone hand `p`.
    pub fn build(menus: &Menus, hands: &[Cards], p: usize) -> Tree {
        Tree::build_some(menus, hands, p, |_| true)
    }

    /// Build the trees for Pone hand `p` against the Dealer hands `wanted`
    /// accepts (tests use small games); other roots stay `NIL`.
    pub fn build_some(
        menus: &Menus,
        hands: &[Cards],
        p: usize,
        wanted: impl Fn(usize) -> bool,
    ) -> Tree {
        let mut t = Tree {
            roots: vec![NIL; 1820],
            nodes: Vec::new(),
            edges: Vec::new(),
        };
        for d in 0..1820 {
            if wanted(d) && feasible(&hands[p], &hands[d]) {
                t.roots[d] = t.grow(menus, State::new(hands[p], hands[d]), p, d);
            }
        }
        t
    }

    pub fn to_bytes(&self) -> Vec<u8> {
        let n = u32::try_from(self.nodes.len() / 2).expect("node count");
        let e = u32::try_from(self.edges.len()).expect("edge count");
        let header = [n, e];
        let words = header
            .iter()
            .chain(&self.roots)
            .chain(&self.nodes)
            .chain(&self.edges);
        words.flat_map(|w| w.to_le_bytes()).collect()
    }

    pub fn from_bytes(bytes: &[u8]) -> Tree {
        assert_eq!(bytes.len() % 4, 0, "Tree read");
        let words: Vec<u32> = bytes
            .as_chunks::<4>()
            .0
            .iter()
            .map(|&c| u32::from_le_bytes(c))
            .collect();
        assert!(words.len() >= 1822, "Tree read");
        let (n, e) = (words[0] as usize, words[1] as usize);
        assert_eq!(words.len(), 1822 + 2 * n + e, "Tree read");
        Tree {
            roots: words[2..1822].to_vec(),
            nodes: words[1822..1822 + 2 * n].to_vec(),
            edges: words[1822 + 2 * n..].to_vec(),
        }
    }

    pub fn read(dir: &Path, p: usize) -> io::Result<Tree> {
        let bytes = std::fs::read(dir.join("trees").join(format!("{p}.bin")))?;
        Ok(Tree::from_bytes(&bytes))
    }
}

/// Action offsets for every menu, in global order, as little-endian `u32`
/// (mirrors the research `offsets.cpp`).
pub fn offsets_bytes(menus: &Menus) -> Vec<u8> {
    menus.offset.iter().flat_map(|o| o.to_le_bytes()).collect()
}

#[cfg(test)]
mod tests {
    use super::super::game::canonical;
    use super::super::menus;
    use super::*;

    /// Dealer 1000 meets a forced play between two of Pone's decisions.
    const DEALERS: [usize; 4] = [0, 500, 1000, 1819];

    /// Menus for one Pone hand and a few Dealer hands; other files stay
    /// empty, which is enough for those trees.
    fn menus_for(p: usize, hands: &[Cards]) -> Menus {
        let files: Vec<Vec<u8>> = (0..FILES)
            .map(|k| {
                if k == p || (k >= 1820 && DEALERS.contains(&(k - 1820))) {
                    menus::build(k, hands)
                } else {
                    Vec::new()
                }
            })
            .collect();
        Menus::from_files(&files)
    }

    #[test]
    fn tree_round_trips_and_every_leaf_matches_a_heuristic_finish() {
        let hands = canonical();
        let p = hands.iter().position(|h| h == &[0, 4, 9, 12]).unwrap();
        let m = menus_for(p, &hands);
        assert!(!m.is_empty() && m.len() == m.parent.len());
        let t = Tree::build_some(&m, &hands, p, |d| DEALERS.contains(&d));
        let again = Tree::from_bytes(&t.to_bytes());
        assert_eq!(again.roots, t.roots);
        assert_eq!(again.nodes, t.nodes);
        assert_eq!(again.edges, t.edges);
        // Following the heuristic at every node must reach the heuristic margin.
        for d in DEALERS {
            if t.roots[d] == NIL {
                continue;
            }
            let mut s = State::new(hands[p], hands[d]);
            let mut id = t.roots[d];
            while id & TAG == 0 {
                let Node { info, first, .. } = t.node(&m, id);
                // Advance the reference state to this decision.
                while s.legal().len() < 2 || 4 - s.n[s.next] >= 3 {
                    let a = s.heuristic();
                    s.play(a);
                }
                assert_eq!(m.history[info], s.history_key());
                let legal = s.legal();
                let choice = s.heuristic().unwrap();
                let i = legal.iter().position(|&r| r == choice).unwrap();
                s.play(Some(choice));
                id = t.edges[first + i];
            }
            s.finish();
            assert_eq!(leaf(id), s.points[0] - s.points[1]);
        }
    }

    #[test]
    fn offsets_count_widths() {
        let files = vec![vec![0u8; 0]; FILES];
        let m = Menus::from_files(&files);
        assert_eq!(m.actions, 0);
        assert!(m.is_empty());
        // A leaf stores its margin's low byte, which must read back signed.
        assert_eq!(leaf(TAG | u32::from((-5i8).cast_unsigned())), -5);
        assert_eq!(leaf(TAG | 127), 127);
        assert_eq!(offsets_bytes(&m).len(), 0);
    }
}
