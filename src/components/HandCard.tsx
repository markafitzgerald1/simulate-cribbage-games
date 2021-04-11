import React from "react";
import Card from "../cribbage/Card";
import Color from "../cribbage/Color";
import { card, redSuit, blackSuit } from "./Card.module.css";
import { handCard } from "./HandCard.module.css";

const CardComponent: React.FunctionComponent<{
  card: Card;
  playHandCard: (card: Card) => void;
}> = (props): JSX.Element => (
  <li
    className={`${card} ${
      props.card.suit.color === Color.RED ? redSuit : blackSuit
    } ${handCard}`}
    onClick={() => props.playHandCard(props.card)}
  >
    {props.card.toString()}
  </li>
);

export default CardComponent;
