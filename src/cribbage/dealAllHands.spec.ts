/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import DECK from "../../src/cribbage/DECK";
import dealAllHands from "../../src/cribbage/dealAllHands";

const deal = () =>
  dealAllHands(
    {
      next: () => 0,
    },
    DECK
  );
const EXPECTED_DEALT_HAND_SIZE = 6;

it(`should deal ${EXPECTED_DEALT_HAND_SIZE} cards to Pone`, () => {
  expect(deal().poneHand.cards).toHaveLength(EXPECTED_DEALT_HAND_SIZE);
});

it(`should deal ${EXPECTED_DEALT_HAND_SIZE} cards to Dealer`, () => {
  expect(deal().dealerHand.cards).toHaveLength(EXPECTED_DEALT_HAND_SIZE);
});
