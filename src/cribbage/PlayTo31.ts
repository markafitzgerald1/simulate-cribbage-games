/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import Card from "./Card";
import Go from "./Go";
import Hand from "./Hand";
import { PlayAction } from "./PlayAction";
import Player from "./Player";

export default class PlayTo31 {
  static readonly FIFTEEN_PLAY_COUNT: number = 15;
  static readonly THIRTY_ONE_PLAY_COUNT: number = 31;
  static readonly MAXIMUM_PLAY_COUNT: number = PlayTo31.THIRTY_ONE_PLAY_COUNT;
  static readonly PLAYER_COUNT: number = 2;
  static readonly PAIRS_POINTS: number[] = [0, 0, 2, 6, 12];
  static readonly FIFTEENS_POINTS: number = 2;
  static readonly THIRTY_ONE_POINTS: number = 1;
  static readonly GO_POINTS: number = 1;

  private constructor(
    readonly playerToPlay: Player,
    readonly playActions: readonly PlayAction[],
    readonly playedCards: readonly Card[],
    readonly count: number,
    readonly mostRecentlyPlayedIndexCount: number,
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

  static create(playerToPlay: Player): PlayTo31 {
    return new PlayTo31(playerToPlay, [], [], 0, 0, 0, 0, 0);
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
    const newPlayedCards: readonly Card[] = [...this.playedCards, card];
    const newMostRecentlyPlayedIndexCount: number =
      newPlayedCards.length >= 2 &&
      newPlayedCards[newPlayedCards.length - 1].index.value ===
        newPlayedCards[newPlayedCards.length - 2].index.value
        ? this.mostRecentlyPlayedIndexCount + 1
        : 1;
    const pairsPoints: number =
      PlayTo31.PAIRS_POINTS[newMostRecentlyPlayedIndexCount];

    let runsPoints: number = 0;
    for (let runLength = newPlayedCards.length; runLength >= 3; runLength--) {
      const sortedRecentPlayIndices = newPlayedCards
        .slice(-runLength)
        .map((play) => play.index);
      sortedRecentPlayIndices.sort((a, b) => a.value - b.value);
      let adjacentIndexCount = 0;
      for (
        let playedCardIndex = 0;
        playedCardIndex < runLength - 1;
        playedCardIndex++
      ) {
        if (
          sortedRecentPlayIndices[playedCardIndex + 1].value -
            sortedRecentPlayIndices[playedCardIndex].value ===
          1
        ) {
          adjacentIndexCount++;
        }
      }
      if (adjacentIndexCount === runLength - 1) {
        runsPoints = runLength;
        break;
      }
    }

    const newCount: number = this.count + card.index.count;
    const fifteensPoints: number =
      newCount === PlayTo31.FIFTEEN_PLAY_COUNT ? PlayTo31.FIFTEENS_POINTS : 0;
    const thirtyOnePoints: number =
      newCount === PlayTo31.THIRTY_ONE_PLAY_COUNT
        ? PlayTo31.THIRTY_ONE_POINTS
        : 0;

    const playPointsScored: number =
      pairsPoints + runsPoints + fifteensPoints + thirtyOnePoints;

    return new PlayTo31(
      this.playerToPlay.next,
      [...this.playActions, card],
      newPlayedCards,
      this.count + card.index.count,
      newMostRecentlyPlayedIndexCount,
      0,
      this.poneScore + (this.poneToPlay() ? playPointsScored : 0),
      this.dealerScore + (this.dealerToPlay() ? playPointsScored : 0)
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
      this.playerToPlay.next,
      [...this.playActions, Go.create()],
      this.playedCards,
      this.count,
      this.mostRecentlyPlayedIndexCount,
      this.currentConsecutiveGoCount + 1,
      this.poneScore + (goScored && this.poneToPlay() ? PlayTo31.GO_POINTS : 0),
      this.dealerScore +
        (goScored && this.dealerToPlay() ? PlayTo31.GO_POINTS : 0)
    );
  }

  private poneToPlay(): boolean {
    return this.playerToPlay === Player.PONE;
  }

  private dealerToPlay(): boolean {
    return this.playerToPlay === Player.DEALER;
  }

  public toString(): string {
    return `playActions=[${this.playActions.map((playAction) =>
      playAction.toString()
    )}] playedCards=[${this.playedCards.map((playedCard) =>
      playedCard.toString()
    )}] count=${this.count} score=[${this.poneScore},${this.dealerScore}]`;
  }
}
