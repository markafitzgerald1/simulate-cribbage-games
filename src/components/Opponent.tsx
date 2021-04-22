/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import React from "react";
import Card from "../cribbage/Card";
import Hand from "../cribbage/Hand";
import HiddenHand from "./HiddenHand";
import ThoughtBubble from "./ThoughtBubble";

interface OpponentProps {
  playedCards: readonly Card[];
  hand: Hand;
  playCard: (card: Card) => void;
}

class Opponent extends React.Component<OpponentProps> {
  render() {
    return (
      <div>
        <h2>Computer</h2>
        <ThoughtBubble thinking={this.props.playedCards.length % 2 === 1} />
        <HiddenHand hand={this.props.hand} />
      </div>
    );
  }

  componentDidUpdate(prevProps: OpponentProps) {
    const isNowOpponentsTurn: Boolean = this.isOpponentsTurn(
      this.props.playedCards
    );
    const wasOpponentsTurn: Boolean = this.isOpponentsTurn(
      prevProps.playedCards
    );
    if (isNowOpponentsTurn && wasOpponentsTurn !== isNowOpponentsTurn) {
      this.props.playCard(this.props.hand.cards[0]);
    }
  }

  isOpponentsTurn(playedCards: readonly Card[]): Boolean {
    return playedCards.length % 2 === 1;
  }
}

export default Opponent;
