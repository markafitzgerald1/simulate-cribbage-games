import Hand from "./Hand";

export default class AllHands {
  constructor(
    public readonly poneHand: Hand,
    public readonly dealerHand: Hand
  ) {}
}
