/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import React from "react";
import Hand from "../cribbage/Hand";
import ThePlay from "../cribbage/ThePlay";

const SayGoButton: React.FunctionComponent<{
  hand: Hand;
  thePlay: ThePlay;
  onClick: () => void;
}> = (props): JSX.Element => (
  <button
    type="button"
    disabled={!props.thePlay.canAddGo(props.hand)}
    onClick={props.onClick}
  >
    Say &apos;Go{"'"}
  </button>
);

export default SayGoButton;
