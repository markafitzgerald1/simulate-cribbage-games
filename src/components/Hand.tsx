import React from "react";
import Hand from "../Hand";
import CardComponent from "./Card";

const HandComponent: React.FunctionComponent<{ hand: Hand }> = (
  props
): JSX.Element => (
  <ul>
    {props.hand.cards.map((card) => (
      <CardComponent card={card} key={card.toString()}></CardComponent>
    ))}
  </ul>
);

export default HandComponent;
