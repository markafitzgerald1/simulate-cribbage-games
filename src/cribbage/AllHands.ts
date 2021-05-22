/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import Hand from "./Hand";

export default class AllHands {
  constructor(
    public readonly poneHand: Hand,
    public readonly dealerHand: Hand
  ) {}

  public toString(): string {
    return `pone=${this.poneHand} dealer=${this.dealerHand}`;
  }
}
