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
import PlayTo31 from "../cribbage/PlayTo31";
import Player from "./Player";

export default class extends React.Component<
  {},
  {
    poneHand: Hand;
    dealerHand: Hand;
    playTo31: PlayTo31;
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
    this.poneSayGo = this.poneSayGo.bind(this);
  }

  render(): JSX.Element {
    return (
      <div>
        <TitleAndH1 title="Play Cribbage" />
        <DealCardsButton dealCards={this.dealCards} />
        <Opponent
          hand={this.state.dealerHand}
          playTo31={this.state.playTo31}
          playCard={this.playDealerCard}
        />
        <PlayedCards playTo31={this.state.playTo31} />
        <Player
          hand={this.state.poneHand}
          playTo31={this.state.playTo31}
          playCard={this.playPoneCard}
          sayGo={this.poneSayGo}
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
    playTo31: PlayTo31;
  } {
    const allHands: AllHands = dealAllHands(randomJsEngine, DECK);
    return {
      poneHand: allHands.poneHand,
      dealerHand: allHands.dealerHand,
      playTo31: PlayTo31.create(),
    };
  }

  playPoneCard(card: Card): void {
    this.setState((state) => ({
      poneHand: state.poneHand.play(card),
      playTo31: state.playTo31.add(card),
    }));
  }

  playDealerCard(card: Card): void {
    this.setState((state) => ({
      dealerHand: state.dealerHand.play(card),
      playTo31: state.playTo31.add(card),
    }));
  }

  poneSayGo(): void {
    this.setState((state) => ({
      playTo31: state.playTo31.addGo(),
    }));
  }
}
