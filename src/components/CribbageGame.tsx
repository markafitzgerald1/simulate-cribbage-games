/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import React from "react";
import { Engine } from "random-js/dist/types";
import { MersenneTwister19937 } from "random-js";
import TitleAndH1 from "./TitleAndH1";
import DealCardsButton from "./DealCardsButton";
import PlayedCards from "./PlayedCards";
import Hand from "../cribbage/Hand";
import Card from "../cribbage/Card";
import DECK from "../cribbage/DECK";
import dealAllHands from "../cribbage/dealAllHands";
import AllHands from "../cribbage/AllHands";
import Opponent from "./Opponent";
import PlayerComponent from "./PlayerComponent";
import ThePlay from "../cribbage/ThePlay";

export default class extends React.Component<
  {},
  {
    poneHand: Hand;
    dealerHand: Hand;
    thePlay: ThePlay;
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
    this.sayGo = this.sayGo.bind(this);
  }

  render(): JSX.Element {
    return (
      <div>
        <TitleAndH1 title="Play Cribbage" />
        <DealCardsButton dealCards={this.dealCards} />
        <Opponent
          hand={this.state.dealerHand}
          thePlay={this.state.thePlay}
          playCard={this.playDealerCard}
          sayGo={this.sayGo}
        />
        <PlayedCards thePlay={this.state.thePlay} />
        <PlayerComponent
          hand={this.state.poneHand}
          thePlay={this.state.thePlay}
          playCard={this.playPoneCard}
          sayGo={this.sayGo}
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

  createCardsJustDealtState(randomJsEngine: Engine): {
    poneHand: Hand;
    dealerHand: Hand;
    thePlay: ThePlay;
  } {
    const allHands: AllHands = dealAllHands(randomJsEngine, DECK);
    return {
      poneHand: allHands.poneHand,
      dealerHand: allHands.dealerHand,
      thePlay: ThePlay.create(),
    };
  }

  playPoneCard(card: Card): void {
    this.setState((state) => ({
      poneHand: state.poneHand.play(card),
      thePlay: state.thePlay.add(card),
    }));
  }

  playDealerCard(card: Card): void {
    this.setState((state) => ({
      dealerHand: state.dealerHand.play(card),
      thePlay: state.thePlay.add(card),
    }));
  }

  sayGo(): void {
    this.setState((state) => ({
      thePlay: state.thePlay.addGo(),
    }));
  }
}
