/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import Card from "./Card";
import { Engine, sample } from "random-js";
import Hand from "./Hand";
import AllHands from "./AllHands";

const DEALT_HAND_SIZE = 4;
const PLAYER_COUNT = 2;

export default (randomJsEngine: Engine, deck: readonly Card[]): AllHands => {
  const cards: readonly Card[] = sample(
    randomJsEngine,
    deck,
    DEALT_HAND_SIZE * PLAYER_COUNT
  );
  return new AllHands(
    new Hand(cards.slice(0, DEALT_HAND_SIZE)),
    new Hand(cards.slice(DEALT_HAND_SIZE))
  );
};
