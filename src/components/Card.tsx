import React from "react";
import Card from "../Card";

const CardComponent: React.FunctionComponent<{ card: Card }> = (
  props
): JSX.Element => <li>{props.card.toString()}</li>;

export default CardComponent;
