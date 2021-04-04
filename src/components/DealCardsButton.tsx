import React from "react";

const DealCardsButton: React.FunctionComponent<{
  dealCards: () => void;
}> = (props): JSX.Element => (
  <button type="button" onClick={() => props.dealCards()}>
    Deal
  </button>
);

export default DealCardsButton;
