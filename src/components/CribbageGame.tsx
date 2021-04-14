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
import dealAllHands from "../cribbage/dealAllHands";
import AllHands from "../cribbage/AllHands";

export default class extends React.Component<
  {},
  {
    poneHand: Hand;
    dealerHand: Hand;
    playedCards: List<Card>;
    randomJsEngine: Engine;
  }
> {
  constructor(props: {}) {
    super(props);

    const randomJsEngine: Engine = MersenneTwister19937.autoSeed();
    this.state = {
      randomJsEngine,
      ...this.createCardsJustDealtState(randomJsEngine),
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
          hand={this.state.poneHand}
          playHandCard={this.playHandCard}
        />
      </div>
    );
  }

  dealAllHands(): AllHands {
    return dealAllHands(this.state.randomJsEngine, DECK);
  }

  dealCards(): void {
    this.setState(this.createCardsJustDealtState(this.state.randomJsEngine));
  }

  createCardsJustDealtState(
    randomJsEngine: Engine
  ): { poneHand: Hand; dealerHand: Hand; playedCards: List<Card> } {
    const allHands: AllHands = dealAllHands(randomJsEngine, DECK);
    return {
      poneHand: allHands.poneHand,
      dealerHand: allHands.dealerHand,
      playedCards: List<Card>(),
    };
  }

  playHandCard(card: Card): void {
    this.setState((state) => ({
      poneHand: new Hand(
        state.poneHand.cards.filter((handCard) => handCard !== card)
      ),
      playedCards: state.playedCards.push(card),
    }));
  }
}
