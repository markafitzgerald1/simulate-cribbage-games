/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import Card from "./Card";
import Game from "./Game";
import Hand from "./Hand";
import Player from "./Player";
import PlayTo31 from "./PlayTo31";
import Points from "./Points";

export default class ThePlay {
  static readonly MAXIMUM_PLAYED_CARD_COUNT: number =
    Player.TOTAL_COUNT * Game.DEALT_HAND_SIZE;

  readonly currentPlayTo31: PlayTo31;

  private constructor(
    readonly playsTo31: readonly PlayTo31[],
    readonly playedCardCount: number,
    readonly lastCardPlayedBy?: Player
  ) {
    this.currentPlayTo31 = playsTo31[playsTo31.length - 1];
  }

  static create(): ThePlay {
    return new ThePlay([PlayTo31.create(Player.PONE)], 0);
  }

  getPlayableCards(playerToPlayHand: Hand): readonly Card[] {
    return this.currentPlayTo31.getPlayableCards(playerToPlayHand);
  }

  add(playerToPlayPlay: Card): ThePlay {
    const updatedPlayedCardCount: number = this.playedCardCount + 1;
    const newCurrentPlayTo31: PlayTo31 =
      this.currentPlayTo31.add(playerToPlayPlay);
    const newPlaysTo31: readonly PlayTo31[] = [
      ...this.playsTo31.slice(0, -1),
      newCurrentPlayTo31,
    ];

    if (updatedPlayedCardCount === ThePlay.MAXIMUM_PLAYED_CARD_COUNT) {
      return new ThePlay(
        newPlaysTo31,
        this.playedCardCount + 1,
        newCurrentPlayTo31.lastPlayerToPlay
      );
    }

    return new ThePlay(newPlaysTo31, this.playedCardCount + 1);
  }

  addGo(): ThePlay {
    const newCurrentPlayTo31: PlayTo31 = this.currentPlayTo31.addGo();
    if (newCurrentPlayTo31.isComplete) {
      return new ThePlay(
        [
          ...this.playsTo31.slice(0, -1),
          newCurrentPlayTo31,
          PlayTo31.create(newCurrentPlayTo31.nextPlayerToPlay),
        ],
        this.playedCardCount
      );
    }

    return new ThePlay(
      [...this.playsTo31.slice(0, -1), newCurrentPlayTo31],
      this.playedCardCount
    );
  }

  get poneScore(): Points {
    return this.getScore(Player.PONE, (playTo31) => playTo31.poneScore);
  }

  get dealerScore(): Points {
    return this.getScore(Player.DEALER, (playTo31) => playTo31.dealerScore);
  }

  get playerToPlay(): Player {
    return this.currentPlayTo31.nextPlayerToPlay;
  }

  private getScore(
    player: Player,
    getPlayerScore: (playTo31: PlayTo31) => Points
  ): Points {
    const lastCardPlayedByPlayer: boolean =
      this.lastCardPlayedBy !== undefined && this.lastCardPlayedBy === player;

    return (
      this.playsTo31.map(getPlayerScore).reduce((prev, curr) => prev + curr) +
      (lastCardPlayedByPlayer ? Game.LAST_CARD_POINTS : 0)
    );
  }

  public toString(): string {
    return `playsTo31=[${this.playsTo31
      .map((playsTo31) => playsTo31.toString())
      .join("; ")}]`;
  }
}
