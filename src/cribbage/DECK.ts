import Card from "./Card";
import Index from "./Index";
import Suit from "./Suit";

const INDICES_PER_SUIT: number = 13;
const SUITS_PER_DECK: number = 4;
const CARDS_PER_DECK: number = INDICES_PER_SUIT * SUITS_PER_DECK;

const DECK: readonly Card[] = Object.freeze(
  Array.from(Array(CARDS_PER_DECK).keys()).map(
    (number) =>
      new Card(
        new Index(number % INDICES_PER_SUIT),
        new Suit(Math.floor(number / INDICES_PER_SUIT))
      )
  )
);

export default DECK;
