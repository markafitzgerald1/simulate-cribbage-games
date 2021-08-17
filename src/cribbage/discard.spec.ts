/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import Game from "./Game";
import createHandOfUniqueCards from "../../test/createHandOfUniqueCards";
import discard from "./discard";

it(`should throw for a hand containing less than ${Game.DEALT_HAND_SIZE} cards`, () => {
  expect(() => {
    discard(createHandOfUniqueCards(Game.KEPT_HAND_SIZE - 1));
  }).toThrow;
});
