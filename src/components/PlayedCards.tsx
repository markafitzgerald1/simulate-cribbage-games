/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import React from "react";
import ThePlay from "../cribbage/ThePlay";
import PlayTo31Component from "./PlayTo31Component";
import { count, playedCards, playedCardList } from "./PlayedCards.module.css";

const PlayedCards: React.FunctionComponent<{
  thePlay?: ThePlay;
}> = (props): JSX.Element => (
  <div className={playedCards}>
    <h3 className={count}>
      Play{props.thePlay ? ` count is ${props.thePlay.count}` : ":"}
    </h3>
    <ul className={playedCardList}>
      {props.thePlay?.playsTo31.map((playTo31, index) => (
        <PlayTo31Component
          playTo31={playTo31}
          key={playTo31.playActions
            .map((playAction) => playAction.toString())
            .join(",")}
        ></PlayTo31Component>
      ))}
    </ul>
  </div>
);

export default PlayedCards;
