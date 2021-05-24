/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import React from "react";
import Card from "../cribbage/Card";
import Hand from "../cribbage/Hand";
import PlayTo31 from "../cribbage/PlayTo31";
import ThePlay from "../cribbage/ThePlay";
import VisibleHandCard from "./VisibleHandCard";

const VisibleHand: React.FunctionComponent<{
  hand: Hand;
  thePlay: ThePlay;
  playCard: (card: Card) => void;
}> = (props): JSX.Element => (
  <div>
    <h2>Your Hand</h2>
    <ul>
      {props.hand.cards.map((card) => (
        <VisibleHandCard
          card={card}
          key={card.toString()}
          thePlay={props.thePlay}
          playHandCard={props.playCard}
        ></VisibleHandCard>
      ))}
    </ul>
  </div>
);

export default VisibleHand;
