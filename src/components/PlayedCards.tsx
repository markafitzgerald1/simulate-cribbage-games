/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import React from "react";
import Go from "../cribbage/Go";
import PlayTo31 from "../cribbage/PlayTo31";
import PlayActionComponent from "./PlayActionComponent";

const PlayedCards: React.FunctionComponent<{
  playTo31: PlayTo31;
}> = (props): JSX.Element => (
  <div>
    <h2>The Play</h2>
    <h3>Count = {props.playTo31.count}</h3>
    <ul>
      {props.playTo31.playActions.map((playAction, index) => (
        <PlayActionComponent
          playAction={playAction}
          key={
            playAction.toString() +
            (playAction instanceof Go ? "-at-index-" + index : "")
          }
        ></PlayActionComponent>
      ))}
    </ul>
  </div>
);

export default PlayedCards;
