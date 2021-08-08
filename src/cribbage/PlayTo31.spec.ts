/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import chai from "chai";
import { describe } from "mocha";
import Game from "./Game";
import PlayTo31 from "./PlayTo31";
import Player from "./Player";
import Hand from "./Hand";
import Card from "./Card";
import Index from "./Index";
import Suit from "./Suit";

const should = chai.should();

describe("PlayTo31", () => {
  describe("getPlayableCards", () => {
    it(`should throw for a hand containing more than ${Game.KEPT_HAND_SIZE} cards`, () => {
      should.throw(() => {
        PlayTo31.create(Player.PONE).getPlayableCards(
          new Hand(
            [...Array(Game.KEPT_HAND_SIZE + 1).keys()].map(
              (cardNumber) =>
                new Card(
                  new Index(Math.floor(cardNumber / Suit.TOTAL_COUNT)),
                  new Suit(cardNumber % Suit.TOTAL_COUNT)
                )
            )
          )
        );
      });
    });
  });
});
