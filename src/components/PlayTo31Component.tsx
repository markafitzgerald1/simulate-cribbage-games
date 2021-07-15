/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import React from "react";
import Go from "../cribbage/Go";
import Player from "../cribbage/Player";
import PlayTo31 from "../cribbage/PlayTo31";
import PlayActionComponent from "./PlayActionComponent";
import { playTo31Component } from "./PlayTo31Component.module.css";

const PlayTo31Component: React.FunctionComponent<{
  playTo31: PlayTo31;
}> = (props): JSX.Element => (
  <ul className={playTo31Component}>
    {props.playTo31.playActions.map((playAction, index) => (
      <PlayActionComponent
        playAction={playAction}
        player={
          index % 2 == props.playTo31.playActions.length % 2
            ? props.playTo31.nextPlayerToPlay
            : props.playTo31.lastPlayerToPlay
        }
        key={
          playAction.toString() +
          (playAction instanceof Go
            ? `-${PlayTo31.name}-action-` + (index + 1)
            : "")
        }
      ></PlayActionComponent>
    ))}
  </ul>
);

export default PlayTo31Component;
