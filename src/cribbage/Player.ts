/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

export default class Player {
  private static readonly PONE_VALUE: number = 0;
  static readonly PONE: Player = new Player(Player.PONE_VALUE);
  private static readonly DEALER_VALUE: number = 1;
  static readonly DEALER: Player = new Player(Player.DEALER_VALUE);
  static readonly TOTAL_COUNT: number = 2;

  readonly value: number;
  readonly nextValue: number;

  private constructor(value: number) {
    if (value < 0 || value >= Player.TOTAL_COUNT) {
      throw new RangeError(
        `Value must be between 0 and ${Player.TOTAL_COUNT}.`
      );
    }

    this.value = value;
    this.nextValue =
      value === Player.PONE_VALUE ? Player.DEALER_VALUE : Player.PONE_VALUE;
  }

  public get isPone(): boolean {
    return this.value === Player.PONE_VALUE;
  }

  public get isDealer(): boolean {
    return this.value === Player.DEALER_VALUE;
  }

  public get next(): Player {
    return this.nextValue === Player.PONE_VALUE ? Player.PONE : Player.DEALER;
  }

  public toString(): string {
    return this.value === 0 ? "Pone" : "Dealer";
  }
}
