/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import React from "react";
import Card from "../cribbage/Card";
import Game from "../cribbage/Game";
import Hand from "../cribbage/Hand";
import ThePlay from "../cribbage/ThePlay";
import SayGoButton from "./SayGoButton";
import VisibleHand from "./VisibleHand";

const PlayerComponent: React.FunctionComponent<{
  hand: Hand;
  thePlay?: ThePlay;
  playCard: (card: Card) => void;
  discardCard: (card: Card) => void;
  sayGo: () => void;
}> = (props): JSX.Element => (
  <div>
    <VisibleHand
      hand={props.hand}
      name="Hand"
      thePlay={props.thePlay}
      playCard={props.playCard}
      discardCard={props.discardCard}
    />
    {props.thePlay && (
      <SayGoButton
        hand={props.hand}
        thePlay={props.thePlay}
        onClick={props.sayGo}
      />
    )}
  </div>
);

export default PlayerComponent;
