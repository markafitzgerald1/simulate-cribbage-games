/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import Card from "./Card";
import Go from "./Go";
import Hand from "./Hand";
import { PlayAction } from "./PlayAction";

export default class PlayTo31 {
  static readonly MAXIMUM_PLAY_COUNT: number = 31;
  static readonly GO_POINTS: number = 1;

  private constructor(
    readonly playActions: readonly PlayAction[],
    readonly count: number,
    readonly currentConsecutiveGoCount: number,
    readonly poneScore: number,
    readonly dealerScore: number
  ) {
    if (this.count > PlayTo31.MAXIMUM_PLAY_COUNT) {
      throw new Error(
        `Invalid play to 31: playActions = ${playActions}, count = ${count}`
      );
    }
  }

  static create(): PlayTo31 {
    return new PlayTo31([], 0, 0, 0, 0);
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
      this.count + card.index.count,
      0,
      0,
      0
    );
  }

  canAddGo(possiblePlayables: Hand): boolean {
    return (
      this.getPlayableCards(possiblePlayables).length === 0 &&
      this.currentConsecutiveGoCount < 2
    );
  }

  addGo(): PlayTo31 {
    const newPlayActions: PlayAction[] = [...this.playActions, Go.create()];
    const newConsecutiveGoCount: number = this.currentConsecutiveGoCount + 1;
    const goScored: boolean = newConsecutiveGoCount === 2;
    const goScoredByPone: boolean = goScored && newPlayActions.length % 2 === 1;
    const goScoredByDealer: boolean =
      goScored && newPlayActions.length % 2 === 0;
    goScored && newPlayActions.length % 2 === 1;
    return new PlayTo31(
      newPlayActions,
      this.count,
      newConsecutiveGoCount,
      goScoredByPone ? PlayTo31.GO_POINTS : 0,
      goScoredByDealer ? PlayTo31.GO_POINTS : 0
    );
  }
}
