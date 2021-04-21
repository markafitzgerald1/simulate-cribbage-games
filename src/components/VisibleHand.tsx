/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import React from "react";
import Card from "../cribbage/Card";
import Hand from "../cribbage/Hand";
import VisibleHandCard from "./VisibleHandCard";

const VisibleHand: React.FunctionComponent<{
  hand: Hand;
  playHandCard: (card: Card) => void;
}> = (props): JSX.Element => (
  <div>
    <h2>Hand</h2>
    <ul>
      {props.hand.cards.map((card) => (
        <VisibleHandCard
          card={card}
          key={card.toString()}
          playHandCard={props.playHandCard}
        ></VisibleHandCard>
      ))}
    </ul>
  </div>
);

export default VisibleHand;
