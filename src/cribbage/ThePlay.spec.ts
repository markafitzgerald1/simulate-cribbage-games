/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import ThePlay from "../../src/cribbage/ThePlay";
import Card from "./Card";
import Game from "./Game";
import Index from "./Index";
import Player from "./Player";
import Suit from "./Suit";

const MAXIMUM_PLAYED_CARD_COUNT = Player.TOTAL_COUNT * Game.KEPT_HAND_SIZE;

test(`cannot contain more than ${MAXIMUM_PLAYED_CARD_COUNT} played cards`, () => {
  expect(() => {
    let thePlay = ThePlay.create();
    [...Array(MAXIMUM_PLAYED_CARD_COUNT + 1).keys()].forEach((value) => {
      thePlay = thePlay.add(
        new Card(
          new Index(Math.floor(value / Suit.TOTAL_COUNT)),
          new Suit(value % Suit.TOTAL_COUNT)
        )
      );
    });
  }).toThrow;
});
