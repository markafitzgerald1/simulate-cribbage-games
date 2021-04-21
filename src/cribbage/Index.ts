/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

export default class Index {
  static readonly TOTAL_COUNT: number = 13;
  static readonly STRINGS: Array<string> = "A23456789TJQK".split("");
  static readonly MAXIMUM_COUNTING_VALUE: number = 10;

  readonly value: number;
  readonly count: number;

  constructor(value: number) {
    if (value < 0 || value >= Index.TOTAL_COUNT) {
      throw new RangeError(`Value must be between 0 and ${Index.TOTAL_COUNT}.`);
    }

    this.value = value;
    this.count = Math.min(value + 1, Index.MAXIMUM_COUNTING_VALUE);
  }

  public toString = (): string => {
    return Index.STRINGS[this.value];
  };
}
