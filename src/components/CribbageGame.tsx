/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import React from "react";
import { Engine } from "random-js/dist/types";
import { MersenneTwister19937 } from "random-js";
import TitleAndH1 from "./TitleAndH1";
import DealCardsButton from "./DealCardsButton";
import PlayedCards from "./PlayedCards";
import VisibleHand from "./VisibleHand";
import Hand from "../cribbage/Hand";
import Card from "../cribbage/Card";
import DECK from "../cribbage/DECK";
import dealAllHands from "../cribbage/dealAllHands";
import AllHands from "../cribbage/AllHands";
import Opponent from "./Opponent";
import PlayToInfiniteCount from "../cribbage/PlayToInfiniteCount";

export default class extends React.Component<
  {},
  {
    poneHand: Hand;
    dealerHand: Hand;
    playToInfiniteCount: PlayToInfiniteCount;
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
    this.playPoneCard = this.playPoneCard.bind(this);
    this.playDealerCard = this.playDealerCard.bind(this);
  }

  render(): JSX.Element {
    return (
      <div>
        <TitleAndH1 title="Play Cribbage" />
        <DealCardsButton dealCards={this.dealCards} />
        <Opponent
          playToInfiniteCount={this.state.playToInfiniteCount}
          hand={this.state.dealerHand}
          playCard={this.playDealerCard}
        />
        <PlayedCards playToInfiniteCount={this.state.playToInfiniteCount} />
        <VisibleHand
          hand={this.state.poneHand}
          canPlayNow={this.state.playToInfiniteCount.cards.length % 2 === 0}
          playHandCard={this.playPoneCard}
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
  ): {
    poneHand: Hand;
    dealerHand: Hand;
    playToInfiniteCount: PlayToInfiniteCount;
  } {
    const allHands: AllHands = dealAllHands(randomJsEngine, DECK);
    return {
      poneHand: allHands.poneHand,
      dealerHand: allHands.dealerHand,
      playToInfiniteCount: new PlayToInfiniteCount([]),
    };
  }

  playPoneCard(card: Card): void {
    this.setState((state) => ({
      poneHand: state.poneHand.play(card),
      playToInfiniteCount: state.playToInfiniteCount.add(card),
    }));
  }

  playDealerCard(card: Card): void {
    this.setState((state) => ({
      dealerHand: state.dealerHand.play(card),
      playToInfiniteCount: state.playToInfiniteCount.add(card),
    }));
  }
}
