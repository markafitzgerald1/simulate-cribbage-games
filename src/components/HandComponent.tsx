import React from "react";
import Card from "../cribbage/Card";
import Hand from "../cribbage/Hand";
import HandCard from "./HandCard";

const HandComponent: React.FunctionComponent<{
  hand: Hand;
  playHandCard: (card: Card) => void;
}> = (props): JSX.Element => (
  <div>
    <h2>Hand</h2>
    <ul>
      {props.hand.cards.map((card) => (
        <HandCard
          card={card}
          key={card.toString()}
          playHandCard={props.playHandCard}
        ></HandCard>
      ))}
    </ul>
  </div>
);

export default HandComponent;
