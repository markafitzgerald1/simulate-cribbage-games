/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */
import React from "react";
import ReactDOM from "react-dom";
import { Helmet } from "react-helmet";

console.log("Hello from simulate-cribbage-games!");

const DealCardsButton = () => <button type="button">Deal</button>;
const TitleAndH1 = (props) => (
  <div>
    <Helmet>
      <title>{props.title}</title>
    </Helmet>
    <h1>{props.title}</h1>
  </div>
);
const CribbageApplication = () => (
  <div>
    <TitleAndH1 title="Play Cribbage" />
    <DealCardsButton />
  </div>
);

ReactDOM.render(<CribbageApplication />, document.getElementById("root"));
