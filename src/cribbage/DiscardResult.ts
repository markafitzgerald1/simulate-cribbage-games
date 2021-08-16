/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import Hand from "./Hand";
import Card from "./Card";

export default class DiscardResult {
  constructor(
    public readonly hand: Hand,
    public readonly discards: [Card, Card]
  ) {}

  public toString(): string {
    return `hand=${this.hand}, discard=${this.discards}`;
  }
}
