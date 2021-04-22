/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import React from "react";
import Card from "../cribbage/Card";
import PlayedCard from "./PlayedCard";

const PlayedCards: React.FunctionComponent<{
  cards: readonly Card[];
}> = (props): JSX.Element => (
  <div>
    <h2>The Play</h2>
    <h3>
      Count ={" "}
      {props.cards
        .map((card) => card.index.count)
        .reduce((prevCount, currCount) => prevCount + currCount, 0)}
    </h3>
    <ul>
      {props.cards.map((card) => (
        <PlayedCard card={card} key={card.toString()}></PlayedCard>
      ))}
    </ul>
  </div>
);

export default PlayedCards;
