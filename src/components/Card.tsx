import React from "react";
import Card from "../cribbage/Card";
import Color from "../cribbage/Color";
import Suit from "../cribbage/Suit";
import { card, redSuit, blackSuit } from "./Card.module.css";

const CardComponent: React.FunctionComponent<{ card: Card }> = (
  props
): JSX.Element => (
  <li
    className={`${card} ${
      props.card.suit.color === Color.RED ? redSuit : blackSuit
    }`}
  >
    {props.card.toString()}
  </li>
);

export default CardComponent;
