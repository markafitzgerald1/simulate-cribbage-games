/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */
import React from "react";
import ReactDOM from "react-dom";
import { Helmet } from "react-helmet";

console.log("Hello from simulate-cribbage-games!");

const TitleAndH1: React.FunctionComponent<{ title: string }> = (
  props
): JSX.Element => (
  <div>
    <Helmet>
      <title>{props.title}</title>
    </Helmet>
    <h1>{props.title}</h1>
  </div>
);

const DealCardsButton: React.FunctionComponent<{
  setCards: (newCards: Array<string>) => void;
}> = (props): JSX.Element => (
  <button
    type="button"
    onClick={() => props.setCards(["KS", "QD", "JH", "5C"])}
  >
    Deal
  </button>
);

class CribbageApplication extends React.Component<
  {},
  { cards: Array<string> }
> {
  constructor(props: {}) {
    super(props);
    this.state = { cards: ["AC", "2D", "3H", "4S"] };
  }

  render() {
    return (
      <div>
        <TitleAndH1 title="Play Cribbage" />
        <DealCardsButton setCards={this.setCards.bind(this)} />
        <div>{this.state.cards.toString()}</div>
      </div>
    );
  }

  setCards(newCards: Array<string>) {
    this.setState({ cards: newCards });
  }
}

ReactDOM.render(<CribbageApplication />, document.getElementById("root"));
