/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import Card from "./Card";
import Go from "./Go";
import Hand from "./Hand";
import { PlayAction } from "./PlayAction";

export default class PlayTo31 {
  static readonly MAXIMUM_PLAY_COUNT: number = 31;
  static readonly PLAYER_COUNT: number = 2;
  static readonly THIRTY_ONE_POINTS: number = 1;
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
    const newCount: number = this.count + card.index.count;
    const thirtyOneScored: boolean = newCount === PlayTo31.MAXIMUM_PLAY_COUNT;
    return new PlayTo31(
      [...this.playActions, card],
      this.count + card.index.count,
      0,
      thirtyOneScored && this.poneToPlay() ? PlayTo31.THIRTY_ONE_POINTS : 0,
      thirtyOneScored && this.dealerToPlay() ? PlayTo31.THIRTY_ONE_POINTS : 0
    );
  }

  canAddGo(possiblePlayables: Hand): boolean {
    return (
      this.getPlayableCards(possiblePlayables).length === 0 &&
      this.currentConsecutiveGoCount < PlayTo31.PLAYER_COUNT
    );
  }

  addGo(): PlayTo31 {
    const goScored: boolean = this.currentConsecutiveGoCount === 1;
    return new PlayTo31(
      [...this.playActions, Go.create()],
      this.count,
      this.currentConsecutiveGoCount + 1,
      this.poneScore + (goScored && this.poneToPlay() ? PlayTo31.GO_POINTS : 0),
      this.dealerScore +
        (goScored && this.dealerToPlay() ? PlayTo31.GO_POINTS : 0)
    );
  }

  private poneToPlay(): boolean {
    return this.playActions.length % PlayTo31.PLAYER_COUNT === 0;
  }

  private dealerToPlay(): boolean {
    return this.playActions.length % PlayTo31.PLAYER_COUNT === 1;
  }
}
