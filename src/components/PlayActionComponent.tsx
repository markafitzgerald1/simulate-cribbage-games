/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import React from "react";
import Card from "../cribbage/Card";
import Color from "../cribbage/Color";
import { PlayAction } from "../cribbage/PlayAction";
import { card, redSuit, blackSuit } from "./Card.module.css";
import { playedCard } from "./PlayedCard.module.css";

const PlayedCard: React.FunctionComponent<{
  playAction: PlayAction;
}> = (props): JSX.Element => (
  <li
    className={`${card} ${
      props.playAction instanceof Card &&
      (props.playAction.suit.color === Color.RED ? redSuit : blackSuit)
    } ${playedCard}`}
  >
    {props.playAction.toString()}
  </li>
);

export default PlayedCard;
