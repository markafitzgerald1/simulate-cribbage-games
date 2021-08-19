/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import React from "react";
import Card from "../cribbage/Card";
import discard from "../cribbage/discard";
import Game from "../cribbage/Game";
import Hand from "../cribbage/Hand";
import ThePlay from "../cribbage/ThePlay";
import HiddenHand from "./HiddenHand";

interface OpponentProps {
  hand: Hand;
  crib: Hand;
  thePlay?: ThePlay;
  playCard: (card: Card) => void;
  discard: (cards: [Card, Card]) => void;
  sayGo: () => void;
}

class Opponent extends React.Component<OpponentProps> {
  render(): React.ReactNode {
    return (
      <div>
        <HiddenHand hand={this.props.crib} name="Crib" />
        <HiddenHand hand={this.props.hand} name="Hand" />
        <h2>Computer: {this.props.thePlay?.dealerScore || 0} points</h2>
      </div>
    );
  }

  private discard = () => {
    if (this.props.hand.cards.length > Game.KEPT_HAND_SIZE) {
      this.props.discard(discard(this.props.hand).discards);
    }
  };

  componentDidMount(): void {
    this.discard();
  }

  componentDidUpdate(prevProps: OpponentProps): void {
    if (!this.props.thePlay) {
      this.discard();
      return;
    }

    const isNowOpponentsTurn: boolean | undefined =
      this.props.thePlay.currentPlayTo31.dealerIsNextToPlay;
    const wasOpponentsTurn: boolean | undefined =
      prevProps.thePlay?.currentPlayTo31.dealerIsNextToPlay;
    if (isNowOpponentsTurn && wasOpponentsTurn !== isNowOpponentsTurn) {
      const playableCards: readonly Card[] =
        this.props.thePlay.getPlayableCards(this.props.hand);
      if (playableCards.length > 0) {
        this.props.playCard(playableCards[0]);
      } else if (this.props.thePlay.canAddGo(this.props.hand)) {
        this.props.sayGo();
      }
    }
  }
}

export default Opponent;
