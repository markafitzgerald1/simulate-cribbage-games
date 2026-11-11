//! Loaded menus and per-Pone-hand game trees.
//!
//! Tree file `p` holds every feasible deal with Pone hand `p`, as little-endian
//! `u32` words: node count `n`, edge count `e`, 1,820 root ids (one per Dealer
//! hand, `u32::MAX` when infeasible), `n` nodes of (global menu index, first
//! edge), then `e` edges. A child id with the high bit set is a terminal; its
//! low byte is the signed Pone-minus-Dealer pegging margin after both players
//! play out their forced last cards.

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
        let total: usize = files
            .iter()
            .map(|menu_file| menu_file.as_ref().len() / RECORD)
            .sum();
        let mut menus = Menus {
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
            let start = u32::try_from(menus.history.len()).expect("menu count");
            menus.starts.push(start);
            for record in bytes.as_chunks::<RECORD>().0 {
                let parent = u32::from_le_bytes(record[8..12].try_into().unwrap());
                menus
                    .history
                    .push(u64::from_le_bytes(record[0..8].try_into().unwrap()));
                menus
                    .parent
                    .push(if parent == NIL { NIL } else { parent + start });
                menus
                    .offset
                    .push(u32::try_from(menus.actions).expect("action offset"));
                menus.stage.push(record[20]);
                menus.width.push(record[21]);
                menus.parent_action.push(record[23]);
                menus.actions += u64::from(record[21]);
            }
        }
        menus
            .starts
            .push(u32::try_from(menus.history.len()).expect("menu count"));
        menus
    }

    /// Read all menu files from `dir/menus/{k}.bin`.
    pub fn load(dir: &Path) -> io::Result<Menus> {
        let files = (0..FILES)
            .map(|file_index| std::fs::read(dir.join("menus").join(format!("{file_index}.bin"))))
            .collect::<io::Result<Vec<_>>>()?;
        Ok(Menus::from_files(&files))
    }

    /// Global menu index for the player to act in `s`.
    fn lookup(&self, state: &State, pone_index: usize, dealer_index: usize) -> u32 {
        let file_index = state.next * 1820
            + if state.next == 1 {
                dealer_index
            } else {
                pone_index
            };
        let (begin, end) = (
            self.starts[file_index] as usize,
            self.starts[file_index + 1] as usize,
        );
        let key = state.history_key();
        let range = &self.history[begin..end];
        let at = range.partition_point(|&candidate| candidate < key);
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
    pub fn node(&self, menus: &Menus, id: u32) -> Node {
        let at = 2 * id as usize;
        let info = self.nodes[at] as usize;
        Node {
            info,
            first: self.nodes[at + 1] as usize,
            off: menus.offset[info] as usize,
            actor: menus.stage[info] % 2,
            width: usize::from(menus.width[info]),
        }
    }

    fn grow(
        &mut self,
        menus: &Menus,
        mut state: State,
        pone_index: usize,
        dealer_index: usize,
    ) -> u32 {
        loop {
            if state.cards_left[0] <= 1 && state.cards_left[1] <= 1 {
                state.finish();
                let margin = state.points[0] - state.points[1];
                assert!((-127..=127).contains(&margin), "Leaf bound");
                return TAG | u32::from(i8::try_from(margin).expect("Leaf bound").cast_unsigned());
            }
            let legal = state.legal();
            if legal.len() < 2 || 4 - state.cards_left[state.next] >= 3 {
                let action = state.forced();
                state.play(action);
                continue;
            }
            let info = menus.lookup(&state, pone_index, dealer_index);
            let id = u32::try_from(self.nodes.len() / 2).expect("node count");
            let first = self.edges.len();
            self.nodes
                .extend_from_slice(&[info, u32::try_from(first).expect("edge count")]);
            self.edges.resize(first + legal.len(), 0);
            for (i, &rank) in legal.iter().enumerate() {
                let mut next = state.clone();
                next.play(Some(rank));
                self.edges[first + i] = self.grow(menus, next, pone_index, dealer_index);
            }
            return id;
        }
    }

    /// Build the trees for Pone hand `p`.
    pub fn build(menus: &Menus, hands: &[Cards], pone_index: usize) -> Tree {
        Tree::build_some(menus, hands, pone_index, |_| true)
    }

    /// Build the trees for Pone hand `p` against the Dealer hands `wanted`
    /// accepts (tests use small games); other roots stay `NIL`.
    pub fn build_some(
        menus: &Menus,
        hands: &[Cards],
        pone_index: usize,
        wanted: impl Fn(usize) -> bool,
    ) -> Tree {
        let mut tree = Tree {
            roots: vec![NIL; 1820],
            nodes: Vec::new(),
            edges: Vec::new(),
        };
        for dealer_index in 0..1820 {
            if wanted(dealer_index) && feasible(&hands[pone_index], &hands[dealer_index]) {
                tree.roots[dealer_index] = tree.grow(
                    menus,
                    State::new(hands[pone_index], hands[dealer_index]),
                    pone_index,
                    dealer_index,
                );
            }
        }
        tree
    }

    pub fn to_bytes(&self) -> Vec<u8> {
        let node_count = u32::try_from(self.nodes.len() / 2).expect("node count");
        let edge_count = u32::try_from(self.edges.len()).expect("edge count");
        let header = [node_count, edge_count];
        let words = header
            .iter()
            .chain(&self.roots)
            .chain(&self.nodes)
            .chain(&self.edges);
        words.flat_map(|word| word.to_le_bytes()).collect()
    }

    pub fn from_bytes(bytes: &[u8]) -> Tree {
        assert_eq!(bytes.len() % 4, 0, "Tree read");
        let words: Vec<u32> = bytes
            .as_chunks::<4>()
            .0
            .iter()
            .map(|&chunk| u32::from_le_bytes(chunk))
            .collect();
        assert!(words.len() >= 1822, "Tree read");
        let (node_count, edge_count) = (words[0] as usize, words[1] as usize);
        assert_eq!(words.len(), 1822 + 2 * node_count + edge_count, "Tree read");
        Tree {
            roots: words[2..1822].to_vec(),
            nodes: words[1822..1822 + 2 * node_count].to_vec(),
            edges: words[1822 + 2 * node_count..].to_vec(),
        }
    }

    pub fn read(dir: &Path, pone_index: usize) -> io::Result<Tree> {
        let bytes = std::fs::read(dir.join("trees").join(format!("{pone_index}.bin")))?;
        Ok(Tree::from_bytes(&bytes))
    }
}

/// Action offsets for every menu, in global order, as little-endian `u32`.
pub fn offsets_bytes(menus: &Menus) -> Vec<u8> {
    menus
        .offset
        .iter()
        .flat_map(|offset| offset.to_le_bytes())
        .collect()
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
    fn menus_for(pone_index: usize, hands: &[Cards]) -> Menus {
        let files: Vec<Vec<u8>> = (0..FILES)
            .map(|file_index| {
                if file_index == pone_index
                    || (file_index >= 1820 && DEALERS.contains(&(file_index - 1820)))
                {
                    menus::build(file_index, hands)
                } else {
                    Vec::new()
                }
            })
            .collect();
        Menus::from_files(&files)
    }

    /// Walk every edge below `id` alongside a replay of the rules: each node
    /// must be the menu for the replayed public history, and each leaf's
    /// margin must equal the replayed hand's. Returns the leaves checked.
    fn check_subtree(tree: &Tree, menus: &Menus, id: u32, mut state: State) -> usize {
        if id & TAG != 0 {
            state.finish();
            assert_eq!(leaf(id), state.points[0] - state.points[1]);
            return 1;
        }
        while state.legal().len() < 2 || 4 - state.cards_left[state.next] >= 3 {
            let action = state.forced();
            state.play(action);
        }
        let Node { info, first, .. } = tree.node(menus, id);
        assert_eq!(menus.history[info], state.history_key());
        let legal = state.legal();
        let mut leaves = 0;
        for (i, &rank) in legal.iter().enumerate() {
            let mut next = state.clone();
            next.play(Some(rank));
            leaves += check_subtree(tree, menus, tree.edges[first + i], next);
        }
        leaves
    }

    #[test]
    fn tree_round_trips_and_every_leaf_matches_a_replay() {
        let hands = canonical();
        let pone_index = hands
            .iter()
            .position(|hand| hand == &[0, 4, 9, 12])
            .unwrap();
        let menus = menus_for(pone_index, &hands);
        assert!(!menus.is_empty() && menus.len() == menus.parent.len());
        let tree = Tree::build_some(&menus, &hands, pone_index, |dealer_index| {
            DEALERS.contains(&dealer_index)
        });
        let again = Tree::from_bytes(&tree.to_bytes());
        assert_eq!(again.roots, tree.roots);
        assert_eq!(again.nodes, tree.nodes);
        assert_eq!(again.edges, tree.edges);
        let mut leaves = 0;
        for dealer_index in DEALERS {
            if tree.roots[dealer_index] == NIL {
                continue;
            }
            let state = State::new(hands[pone_index], hands[dealer_index]);
            leaves += check_subtree(&tree, &menus, tree.roots[dealer_index], state);
        }
        assert!(leaves > 100, "only {leaves} leaves checked");
    }

    #[test]
    fn offsets_count_widths() {
        let files = vec![vec![0u8; 0]; FILES];
        let menus = Menus::from_files(&files);
        assert_eq!(menus.actions, 0);
        assert!(menus.is_empty());
        // A leaf stores its margin's low byte, which must read back signed.
        assert_eq!(leaf(TAG | u32::from((-5i8).cast_unsigned())), -5);
        assert_eq!(leaf(TAG | 127), 127);
        assert_eq!(offsets_bytes(&menus).len(), 0);
    }
}
