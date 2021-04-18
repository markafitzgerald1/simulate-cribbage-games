import React from "react";
import Card from "../cribbage/Card";
import PlayedCard from "./PlayedCard";

const PlayedCards: React.FunctionComponent<{
  cards: readonly Card[];
}> = (props): JSX.Element => (
  <div>
    <h2>Play</h2>
    <ul>
      {props.cards.map((card) => (
        <PlayedCard card={card} key={card.toString()}></PlayedCard>
      ))}
    </ul>
  </div>
);

export default PlayedCards;
