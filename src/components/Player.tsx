/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import React from "react";
import Card from "../cribbage/Card";
import Hand from "../cribbage/Hand";
import PlayTo31 from "../cribbage/PlayTo31";
import SayGoButton from "./SayGoButton";
import VisibleHand from "./VisibleHand";

const Player: React.FunctionComponent<{
  hand: Hand;
  playTo31: PlayTo31;
  playCard: (card: Card) => void;
  sayGo: () => void;
}> = (props): JSX.Element => (
  <div>
    <VisibleHand
      hand={props.hand}
      playTo31={props.playTo31}
      playCard={props.playCard}
    />
    <SayGoButton
      hand={props.hand}
      playTo31={props.playTo31}
      onClick={props.sayGo}
    />
  </div>
);

export default Player;
