/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import Card from "./Card";
import Hand from "./Hand";
import Player from "./Player";
import PlayTo31 from "./PlayTo31";
import Points from "./Points";

export default class ThePlay {
  readonly currentPlayTo31: PlayTo31;

  private constructor(readonly playsTo31: readonly PlayTo31[]) {
    this.currentPlayTo31 = playsTo31[playsTo31.length - 1];
  }

  static create(): ThePlay {
    return new ThePlay([PlayTo31.create(Player.PONE)]);
  }

  getPlayableCards(playerToPlayHand: Hand): readonly Card[] {
    return this.currentPlayTo31.getPlayableCards(playerToPlayHand);
  }

  add(playerToPlayPlay: Card): ThePlay {
    return new ThePlay([
      ...this.playsTo31.slice(0, -1),
      this.currentPlayTo31.add(playerToPlayPlay),
    ]);
  }

  addGo(): ThePlay {
    const newCurrentPlayTo31: PlayTo31 = this.currentPlayTo31.addGo();
    if (newCurrentPlayTo31.isComplete) {
      return new ThePlay([
        ...this.playsTo31.slice(0, -1),
        newCurrentPlayTo31,
        PlayTo31.create(newCurrentPlayTo31.playerToPlay),
      ]);
    }

    return new ThePlay([...this.playsTo31.slice(0, -1), newCurrentPlayTo31]);
  }

  get poneScore(): Points {
    return this.playerScore((playTo31) => playTo31.poneScore);
  }

  get dealerScore(): Points {
    return this.playerScore((playTo31) => playTo31.dealerScore);
  }

  get playerToPlay(): Player {
    return this.currentPlayTo31.playerToPlay;
  }

  private playerScore(getPlayerScore: (playTo31: PlayTo31) => Points): Points {
    return this.playsTo31
      .map(getPlayerScore)
      .reduce((prev, curr) => prev + curr);
  }

  public toString(): string {
    return `playsTo31=[${this.playsTo31
      .map((playsTo31) => playsTo31.toString())
      .join("; ")}]`;
  }
}
