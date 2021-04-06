import React from "react";
import Card from "../cribbage/Card";
import { card } from "./Card.module.css";

const CardComponent: React.FunctionComponent<{ card: Card }> = (
  props
): JSX.Element => <li className={card}>{props.card.toString()}</li>;

export default CardComponent;
