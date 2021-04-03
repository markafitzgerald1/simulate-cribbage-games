import React from "react";
import Card from "../Card";
import CardComponent from "./CardComponent";

const HandComponent: React.FunctionComponent<{ cards: Card[] }> = (
  props
): JSX.Element => (
  <ul>
    {props.cards.map((card) => (
      <CardComponent card={card} key={card.toString()}></CardComponent>
    ))}
  </ul>
);

export default HandComponent;
