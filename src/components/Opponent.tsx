/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import React from "react";
import Card from "../cribbage/Card";
import Hand from "../cribbage/Hand";
import PlayTo31 from "../cribbage/PlayTo31";
import ThePlay from "../cribbage/ThePlay";
import HiddenHand from "./HiddenHand";
import ThoughtBubble from "./ThoughtBubble";

interface OpponentProps {
  hand: Hand;
  thePlay: ThePlay;
  playCard: (card: Card) => void;
  sayGo: () => void;
}

class Opponent extends React.Component<OpponentProps> {
  render() {
    return (
      <div>
        <h2>Computer</h2>
        <ThoughtBubble thinking={this.props.thePlay.dealerIsNextToPlay} />
        <HiddenHand hand={this.props.hand} />
      </div>
    );
  }

  componentDidUpdate(prevProps: OpponentProps) {
    const isNowOpponentsTurn: boolean =
      this.props.thePlay.currentPlayTo31.dealerIsNextToPlay;
    const wasOpponentsTurn: boolean =
      prevProps.thePlay.currentPlayTo31.dealerIsNextToPlay;
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
