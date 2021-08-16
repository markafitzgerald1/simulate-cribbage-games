/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import DiscardResult from "./DiscardResult";
import Hand from "./Hand";
import Game from "./Game";

export default (hand: Hand): DiscardResult => {
  if (hand.cards.length !== Game.DEALT_HAND_SIZE) {
    throw new RangeError(
      `Hand from which to discard must contain exactly ${Game.DEALT_HAND_SIZE} cards.`
    );
  }

  return new DiscardResult(new Hand(hand.cards.slice(0, Game.KEPT_HAND_SIZE)), [
    hand.cards[Game.KEPT_HAND_SIZE],
    hand.cards[Game.KEPT_HAND_SIZE + 1],
  ]);
};
