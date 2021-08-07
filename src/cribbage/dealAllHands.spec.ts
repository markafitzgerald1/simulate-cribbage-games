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
  const DEALT_CARDS_LEN = 6;

  it.skip(`should deal ${DEALT_CARDS_LEN} cards to Pone`, () => {
    deal().poneHand.cards.should.have.length(DEALT_CARDS_LEN);
  });

  it.skip(`should deal ${DEALT_CARDS_LEN} cards to Dealer`, () => {
    deal().dealerHand.cards.should.have.length(DEALT_CARDS_LEN);
  });
});
