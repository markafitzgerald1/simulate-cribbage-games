/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import Card from "./Card";
import Index from "./Index";
import Suit from "./Suit";

const INDICES_PER_SUIT = 13;
const SUITS_PER_DECK = 4;
const CARDS_PER_DECK: number = INDICES_PER_SUIT * SUITS_PER_DECK;

const DECK: readonly Card[] = Array.from(Array(CARDS_PER_DECK).keys()).map(
  (number) =>
    new Card(
      new Index(number % INDICES_PER_SUIT),
      new Suit(Math.floor(number / INDICES_PER_SUIT))
    )
);

export default DECK;
