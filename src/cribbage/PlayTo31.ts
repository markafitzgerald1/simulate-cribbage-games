/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import Card from "./Card";
import Go from "./Go";
import Hand from "./Hand";
import { PlayAction } from "./PlayAction";

export default class PlayTo31 {
  static readonly MAXIMUM_PLAY_COUNT: number = 31;

  private constructor(
    readonly playActions: readonly PlayAction[],
    readonly count: number
  ) {
    if (this.count > PlayTo31.MAXIMUM_PLAY_COUNT) {
      throw new Error(
        `Invalid play to 31: playActions = ${playActions}, count = ${count}`
      );
    }
  }

  static create(): PlayTo31 {
    return new PlayTo31([], 0);
  }

  isPlayable(card: Card): boolean {
    return this.count + card.index.count <= PlayTo31.MAXIMUM_PLAY_COUNT;
  }

  getPlayableCards(possiblePlayables: Hand): readonly Card[] {
    return possiblePlayables.cards.filter(
      (possiblePlayable: Card) =>
        this.count + possiblePlayable.index.count <= PlayTo31.MAXIMUM_PLAY_COUNT
    );
  }

  add(card: Card): PlayTo31 {
    return new PlayTo31(
      [...this.playActions, card],
      this.count + card.index.count
    );
  }

  addGo(): PlayTo31 {
    return new PlayTo31([...this.playActions, Go.create()], this.count);
  }
}
