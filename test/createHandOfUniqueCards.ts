/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import Hand from "../src/cribbage/Hand";
import Suit from "../src/cribbage/Suit";
import Index from "../src/cribbage/Index";
import Card from "../src/cribbage/Card";

export default (cardCount: number): Hand =>
  new Hand(
    [...Array(cardCount).keys()].map(
      (cardNumber) =>
        new Card(
          new Index(Math.floor(cardNumber / Suit.TOTAL_COUNT)),
          new Suit(cardNumber % Suit.TOTAL_COUNT)
        )
    )
  );
