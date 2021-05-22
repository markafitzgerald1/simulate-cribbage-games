/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

export default class Go {
  private static SINGLETON: Go = new Go();

  private constructor() {}

  public static create(): Go {
    return this.SINGLETON;
  }

  public toString(): string {
    return "Go";
  }
}
