import React from "react";
import { Engine } from "random-js/dist/types";
import { MersenneTwister19937 } from "random-js";
import TitleAndH1 from "./TitleAndH1";
import DealCardsButton from "./DealCardsButton";
import HandComponent from "./Hand";
import Hand from "../cribbage/Hand";
import DECK from "../cribbage/DECK";
import dealHand from "../cribbage/dealHand";

export default class extends React.Component<
  {},
  { hand: Hand; randomJsEngine: Engine }
> {
  constructor(props: {}) {
    super(props);
    const randomJsEngine: Engine = MersenneTwister19937.autoSeed();
    const hand: Hand = dealHand(randomJsEngine, DECK);
    this.state = {
      hand,
      randomJsEngine,
    };
    this.dealCards = this.dealCards.bind(this);
  }

  render(): JSX.Element {
    return (
      <div>
        <TitleAndH1 title="Play Cribbage" />
        <DealCardsButton dealCards={this.dealCards} />
        <HandComponent hand={this.state.hand} />
      </div>
    );
  }

  dealHand(): Hand {
    return dealHand(this.state.randomJsEngine, DECK);
  }

  dealCards(): void {
    this.setState({ hand: this.dealHand() });
  }
}
