/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */
import React from "react";
import ReactDOM from "react-dom";

console.log("Hello from simulate-cribbage-games!");

function DealCardsButton() {
  return <button type="button">Deal</button>;
}

ReactDOM.render(
  <div>
    <h1>Play Cribbage</h1>
    <DealCardsButton />
  </div>,
  document.getElementById("root")
);
