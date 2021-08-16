/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import React from "react";
import Card from "../cribbage/Card";
import Hand from "../cribbage/Hand";
import ThePlay from "../cribbage/ThePlay";
import VisibleHandCard from "./VisibleHandCard";
import { visibleHandHand } from "./VisibleHand.module.css";

const VisibleHand: React.FunctionComponent<{
  hand: Hand;
  name: string;
  thePlay?: ThePlay;
  playCard: (card: Card) => void;
  discardCard: (card: Card) => void;
}> = (props): JSX.Element => (
  <div>
    <h2>Player: {props.thePlay?.poneScore || 0} points</h2>
    <div className={visibleHandHand}>
      <span>{props.name}</span>
      <ul>
        {props.hand.cards.map((card) => (
          <VisibleHandCard
            card={card}
            key={card.toString()}
            thePlay={props.thePlay}
            playHandCard={props.playCard}
            discardHandCard={props.discardCard}
          ></VisibleHandCard>
        ))}
      </ul>
    </div>
  </div>
);

export default VisibleHand;
