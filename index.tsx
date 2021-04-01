// index.tsx
import React from "react";
import ReactDOM from "react-dom";

console.log("Hello from tsx!");

function DealCardsButton() {
  return <button type="button">Deal</button>;
}

ReactDOM.render(
  <div>
    <h1>Play Cribbage</h1>
    <DealCardsButton />
  </div>,
  document.getElementById("root")
);
