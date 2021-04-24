/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import React from "react";
import Card from "../cribbage/Card";
import Color from "../cribbage/Color";
import PlayTo31 from "../cribbage/PlayTo31";
import { card, redSuit, blackSuit } from "./Card.module.css";
import { playable, notPlayable } from "./VisibleHandCard.module.css";

const canPlayNow = (card: Card, playTo31: PlayTo31): boolean =>
  playTo31.cards.length % 2 === 0 && playTo31.isPlayable(card);

const VisibleHandCard: React.FunctionComponent<{
  card: Card;
  playTo31: PlayTo31;
  playHandCard: (card: Card) => void;
}> = (props): JSX.Element => (
  <li
    className={`${card} ${
      props.card.suit.color === Color.RED ? redSuit : blackSuit
    } ${canPlayNow(props.card, props.playTo31) ? playable : notPlayable}`}
    onClick={() =>
      canPlayNow(props.card, props.playTo31) && props.playHandCard(props.card)
    }
  >
    {props.card.toString()}
  </li>
);

export default VisibleHandCard;
