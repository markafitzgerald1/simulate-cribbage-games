/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import Card from "./Card";

export default class PlayToInfiniteCount {
  constructor(public readonly cards: readonly Card[]) {}

  add(card: Card): PlayToInfiniteCount {
    return new PlayToInfiniteCount([...this.cards, card]);
  }
}
