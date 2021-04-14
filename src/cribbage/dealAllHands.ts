import Card from "./Card";
import { Engine, sample } from "random-js";
import Hand from "./Hand";
import { List } from "immutable";
import AllHands from "./AllHands";

const DEALT_HAND_SIZE = 4;
const PLAYER_COUNT = 2;

export default (randomJsEngine: Engine, deck: readonly Card[]): AllHands => {
  const cards: List<Card> = List<Card>(
    sample(randomJsEngine, deck, DEALT_HAND_SIZE * PLAYER_COUNT)
  );
  return new AllHands(
    new Hand(cards.slice(0, DEALT_HAND_SIZE)),
    new Hand(cards.slice(DEALT_HAND_SIZE))
  );
};
