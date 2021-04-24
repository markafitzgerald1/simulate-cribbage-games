/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import React from "react";
import Hand from "../cribbage/Hand";
import PlayTo31 from "../cribbage/PlayTo31";

const SayGoButton: React.FunctionComponent<{
  hand: Hand;
  playTo31: PlayTo31;
  onClick: () => void;
}> = (props): JSX.Element => (
  <button
    type="button"
    disabled={props.playTo31.getPlayableCards(props.hand).length > 0}
    onClick={props.onClick}
  >
    Say 'Go'
  </button>
);

export default SayGoButton;
