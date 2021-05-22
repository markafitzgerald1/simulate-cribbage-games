/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import Card from "./Card";

export default class Hand {
  constructor(public readonly cards: readonly Card[]) {}

  play(card: Card): Hand {
    return new Hand(this.cards.filter((handCard) => handCard !== card));
  }

  public toString(): string {
    return `[${this.cards.map((card) => card.toString())}]`;
  }
}
