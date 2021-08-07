/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import chai from "chai";
import { describe } from "mocha";
import DECK from "../../src/cribbage/DECK";
import dealAllHands from "../../src/cribbage/dealAllHands";

chai.should();

describe("dealAllHands", function () {
  const deal = () =>
    dealAllHands(
      {
        next: () => 0,
      },
      DECK
    );
  const EXPECTED_DEALT_HAND_SIZE = 6;

  it(`should deal ${EXPECTED_DEALT_HAND_SIZE} cards to Pone`, () => {
    deal().poneHand.cards.should.have.length(EXPECTED_DEALT_HAND_SIZE);
  });

  it(`should deal ${EXPECTED_DEALT_HAND_SIZE} cards to Dealer`, () => {
    deal().dealerHand.cards.should.have.length(EXPECTED_DEALT_HAND_SIZE);
  });
});
