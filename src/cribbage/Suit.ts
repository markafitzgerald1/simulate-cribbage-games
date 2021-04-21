/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import Color from "./Color";

export default class Suit {
  static readonly TOTAL_COUNT: number = 4;
  static readonly STRINGS: Array<string> = "♣♦♥♠".split("");
  static readonly CLUBS: Suit = new Suit(0);
  static readonly DIAMONDS: Suit = new Suit(1);
  static readonly HEARTS: Suit = new Suit(2);
  static readonly SPADES: Suit = new Suit(3);

  readonly value: number;
  readonly color: Color;

  constructor(value: number) {
    if (value < 0 || value >= Suit.TOTAL_COUNT) {
      throw new RangeError(`Value must be between 0 and ${Suit.TOTAL_COUNT}.`);
    }

    this.value = value;
    this.color = [0, Suit.TOTAL_COUNT - 1].includes(value)
      ? Color.BLACK
      : Color.RED;
  }

  public toString = (): string => {
    return Suit.STRINGS[this.value];
  };
}
