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
import Game from "../cribbage/Game";
import Player from "../cribbage/Player";

export default class CribbageGame extends React.Component<
  Record<string, never>,
  {
    poneHand: Hand;
    dealerHand: Hand;
    crib: Hand;
    thePlay?: ThePlay;
    randomJsEngine: Engine;
  }
> {
  constructor(props: Record<string, never>) {
    super(props);

    const randomJsEngine: Engine = MersenneTwister19937.autoSeed();
    this.state = {
      randomJsEngine,
      ...this.createCardsJustDealtState(randomJsEngine),
    };

    this.dealCards = this.dealCards.bind(this);
    this.playPoneCard = this.playPoneCard.bind(this);
    this.discardPoneCard = this.discardPoneCard.bind(this);
    this.playDealerCard = this.playDealerCard.bind(this);
    this.discardDealerCards = this.discardDealerCards.bind(this);
    this.sayGo = this.sayGo.bind(this);
  }

  render(): JSX.Element {
    return (
      <div>
        <TitleAndH1 title="Play Cribbage" />
        <DealCardsButton dealCards={this.dealCards} />
        <Opponent
          hand={this.state.dealerHand}
          crib={this.state.crib}
          thePlay={this.state.thePlay}
          playCard={this.playDealerCard}
          discard={this.discardDealerCards}
          sayGo={this.sayGo}
        />
        <PlayedCards thePlay={this.state.thePlay} />
        <PlayerComponent
          hand={this.state.poneHand}
          thePlay={this.state.thePlay}
          playCard={this.playPoneCard}
          discardCard={this.discardPoneCard}
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
    crib: Hand;
    thePlay?: ThePlay;
  } {
    const allHands: AllHands = dealAllHands(randomJsEngine, DECK);
    return {
      poneHand: allHands.poneHand,
      dealerHand: allHands.dealerHand,
      crib: new Hand([]),
      thePlay: undefined,
    };
  }

  private playCard(player: Player, card: Card): void {
    if (!this.state.thePlay) {
      throw new Error(
        `Cannot play a ${player.toString()} card before the play phase of game play has started.`
      );
    }

    this.setState((state) => {
      return {
        poneHand: player.isPone ? state.poneHand.remove(card) : state.poneHand,
        dealerHand: player.isDealer
          ? state.dealerHand.remove(card)
          : state.dealerHand,
        thePlay: state.thePlay && state.thePlay.add(card),
      };
    });
  }

  playPoneCard(card: Card): void {
    this.playCard(Player.PONE, card);
  }

  playDealerCard(card: Card): void {
    this.playCard(Player.DEALER, card);
  }

  private assertCanDiscard(player: Player): void {
    if (this.state.thePlay) {
      throw new Error(
        `Cannot discard a ${player.toString()} card after the play phase of game play has started.`
      );
    }
  }

  discardPoneCard(card: Card): void {
    this.assertCanDiscard(Player.PONE);
    this.setState((state) => ({
      poneHand: state.poneHand.remove(card),
      crib: state.crib.add(card),
      thePlay:
        state.poneHand.cards.length + state.dealerHand.cards.length ==
        Game.KEPT_HAND_SIZE * 2 + 1
          ? ThePlay.create()
          : undefined,
    }));
  }

  discardDealerCards(cards: [Card, Card]): void {
    this.assertCanDiscard(Player.DEALER);
    this.setState((state) => ({
      dealerHand: state.dealerHand.remove(cards[0]).remove(cards[1]),
      crib: state.crib.add(cards[0]).add(cards[1]),
      thePlay:
        state.poneHand.cards.length + state.dealerHand.cards.length ==
        Game.KEPT_HAND_SIZE * 2 + 2
          ? ThePlay.create()
          : undefined,
    }));
  }

  sayGo(): void {
    this.setState((state) => ({
      thePlay: state.thePlay && state.thePlay.addGo(),
    }));
  }
}
