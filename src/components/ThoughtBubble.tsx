/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import React from "react";
import Card from "../cribbage/Card";
import Hand from "../cribbage/Hand";

const ThoughtBubble: React.FunctionComponent<{
  thinking: Boolean;
}> = (props): JSX.Element => (
  <div>
    <h3>{props.thinking ? "thinking..." : "waiting..."}</h3>
  </div>
);

export default ThoughtBubble;
