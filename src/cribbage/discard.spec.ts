/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import chai from "chai";
import { describe } from "mocha";
import Game from "./Game";
import createHandOfUniqueCards from "../../test/createHandOfUniqueCards";
import discard from "./discard";

const should = chai.should();

describe("discard", function () {
  it(`should throw for a hand containing less than ${Game.DEALT_HAND_SIZE} cards`, () => {
    should.throw(() => {
      discard(createHandOfUniqueCards(Game.KEPT_HAND_SIZE - 1));
    });
  });
});
