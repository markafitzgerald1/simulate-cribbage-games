import React from "react";
import { List } from "immutable";
import { Engine } from "random-js/dist/types";
import { MersenneTwister19937 } from "random-js";
import TitleAndH1 from "./TitleAndH1";
import DealCardsButton from "./DealCardsButton";
import PlayedCards from "./PlayedCards";
import HandComponent from "./HandComponent";
import Hand from "../cribbage/Hand";
import Card from "../cribbage/Card";
import DECK from "../cribbage/DECK";
import dealHand from "../cribbage/dealHand";

export default class extends React.Component<
  {},
  { hand: Hand; playedCards: List<Card>; randomJsEngine: Engine }
> {
  constructor(props: {}) {
    super(props);
    const randomJsEngine: Engine = MersenneTwister19937.autoSeed();
    const hand: Hand = dealHand(randomJsEngine, DECK);
    this.state = {
      hand,
      playedCards: List<Card>(),
      randomJsEngine,
    };
    this.dealCards = this.dealCards.bind(this);
    this.playHandCard = this.playHandCard.bind(this);
  }

  render(): JSX.Element {
    return (
      <div>
        <TitleAndH1 title="Play Cribbage" />
        <DealCardsButton dealCards={this.dealCards} />
        <PlayedCards cards={this.state.playedCards} />
        <HandComponent
          hand={this.state.hand}
          playHandCard={this.playHandCard}
        />
      </div>
    );
  }

  dealHand(): Hand {
    return dealHand(this.state.randomJsEngine, DECK);
  }

  dealCards(): void {
    this.setState({ hand: this.dealHand(), playedCards: List<Card>() });
  }

  playHandCard(card: Card): void {
    this.setState((state) => ({
      hand: new Hand(state.hand.cards.filter((handCard) => handCard !== card)),
      playedCards: state.playedCards.push(card),
    }));
  }
}
