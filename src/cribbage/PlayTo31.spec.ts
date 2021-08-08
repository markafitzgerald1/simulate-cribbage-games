/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import chai from "chai";
import { describe } from "mocha";
import Game from "./Game";
import PlayTo31 from "./PlayTo31";
import Player from "./Player";
import createHandOfUniqueCards from "../../test/createHandOfUniqueCards";

const should = chai.should();

describe("PlayTo31", () => {
  describe("getPlayableCards", () => {
    it(`should throw for a hand containing more than ${Game.KEPT_HAND_SIZE} cards`, () => {
      should.throw(() => {
        PlayTo31.create(Player.PONE).getPlayableCards(
          createHandOfUniqueCards(Game.KEPT_HAND_SIZE + 1)
        );
      });
    });
  });
});
