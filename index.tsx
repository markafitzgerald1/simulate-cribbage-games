/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */
import React from "react";
import ReactDOM from "react-dom";
import { Helmet } from "react-helmet";
import Card from "./src/Card";
import Index from "./src/Index";
import Suit from "./src/Suit";

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
  setCards: (newCards: Array<Card>) => void;
}> = (props): JSX.Element => (
  <button
    type="button"
    onClick={() =>
      props.setCards([
        new Card(new Index(12), new Suit(3)),
        new Card(new Index(11), new Suit(2)),
        new Card(new Index(10), new Suit(1)),
        new Card(new Index(4), new Suit(0)),
      ])
    }
  >
    Deal
  </button>
);

class CribbageApplication extends React.Component<{}, { cards: Array<Card> }> {
  constructor(props: {}) {
    super(props);
    this.state = {
      cards: [
        new Card(new Index(0), new Suit(0)),
        new Card(new Index(1), new Suit(1)),
        new Card(new Index(2), new Suit(2)),
        new Card(new Index(3), new Suit(3)),
      ],
    };
    this.setCards = this.setCards.bind(this);
  }

  render() {
    return (
      <div>
        <TitleAndH1 title="Play Cribbage" />
        <DealCardsButton setCards={this.setCards} />
        <div>{this.state.cards.toString()}</div>
      </div>
    );
  }

  setCards(newCards: Array<Card>) {
    this.setState({ cards: newCards });
  }
}

ReactDOM.render(<CribbageApplication />, document.getElementById("root"));
