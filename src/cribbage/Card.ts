/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import Index from "./Index";
import Suit from "./Suit";

export default class Card {
  constructor(public readonly index: Index, public readonly suit: Suit) {}

  public toString = (): string => {
    return `${this.index}${this.suit}`;
  };
}
