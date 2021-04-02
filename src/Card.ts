import Index from "./Index";
import Suit from "./Suit";

export default class Card {
  constructor(public readonly index: Index, public readonly suit: Suit) {}

  public toString = (): string => {
    return `${this.index}${this.suit}`;
  };
}
