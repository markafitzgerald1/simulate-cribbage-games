/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import React from "react";
import Go from "../cribbage/Go";
import PlayTo31 from "../cribbage/PlayTo31";
import PlayActionComponent from "./PlayActionComponent";

const PlayTo31Component: React.FunctionComponent<{
  playTo31: PlayTo31;
}> = (props): JSX.Element => (
  <div>
    <ul>
      {props.playTo31.playActions.map((playAction, index) => (
        <PlayActionComponent
          playAction={playAction}
          key={
            playAction.toString() +
            (playAction instanceof Go
              ? `-${PlayTo31.name}-action-` + (index + 1)
              : "")
          }
        ></PlayActionComponent>
      ))}
    </ul>
  </div>
);

export default PlayTo31Component;
