/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import React from "react";
import md5 from "md5";
import Hand from "../cribbage/Hand";
import HiddenHandCard from "./HiddenHandCard";
import { hiddenHand } from "./HiddenHand.module.css";

const HiddenHand: React.FunctionComponent<{
  hand: Hand;
  name: string;
}> = (props): JSX.Element => (
  <div className={hiddenHand}>
    <span>{props.name}</span>
    <ul>
      {props.hand.cards.map((card) => (
        <HiddenHandCard card={card} key={md5(card.toString())}></HiddenHandCard>
      ))}
    </ul>
  </div>
);

export default HiddenHand;
