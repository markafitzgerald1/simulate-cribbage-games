/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import { expect, test } from "@playwright/test";

test("discard, finish a random hand, and deal again without browser errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Play Cribbage" })).toBeVisible();
  const hand = page.getByTestId("player-hand").getByRole("listitem");
  const history = page.getByTestId("play-history");
  const actions = history.getByRole("listitem");
  const playedCards = actions.filter({ hasNotText: /^Go$/ });
  const countHeading = page.getByRole("heading", { name: /^Play count is / });
  const go = page.getByRole("button", { name: "Say 'Go'", exact: true });

  await expect(hand).toHaveCount(6);
  await hand.first().click();
  await expect(hand).toHaveCount(5);
  await hand.first().click();
  await expect(hand).toHaveCount(4);
  await expect(countHeading).toHaveText("Play count is 0");

  // Four plays plus at most two Go actions per count reset fit well below 24.
  for (let turn = 0; turn < 24; turn++) {
    const countText = await countHeading.innerText();
    expect(countText).toMatch(/^Play count is (?:[0-9]|[12][0-9]|3[01])$/);
    // Check every retained sequence, including opponent plays between clicks.
    for (const sequence of await history.getByRole("list").all()) {
      let total = 0;
      for (const action of await sequence.getByRole("listitem").allTextContents()) {
        if (action === "Go") continue;
        const rank = action.slice(0, -1);
        total += rank === "A" ? 1 : /^[TJQK]$/.test(rank) ? 10 : Number(rank);
        expect(total).toBeLessThanOrEqual(31);
        expect(total).toBeGreaterThan(0);
      }
    }
    if (await playedCards.count() === 8) break;

    const playable = hand.and(page.locator('[aria-disabled="false"]'));
    if (await playable.count() > 0) {
      const remaining = await hand.count();
      const card = await playable.first().innerText();
      await playable.first().click();
      await expect(hand).toHaveCount(remaining - 1);
      await expect(history.getByText(card, { exact: true })).toBeVisible();
    } else {
      await expect(go).toBeEnabled();
      const previousActions = await actions.count();
      await go.click();
      await expect.poll(() => actions.count()).toBeGreaterThan(previousActions);
    }
  }

  await expect(playedCards).toHaveCount(8);
  await expect(hand).toHaveCount(0);
  await expect(go).toBeDisabled();
  for (const player of ["Player", "Computer"]) {
    await expect(page.getByRole("heading", { name: new RegExp(`^${player}:`) }))
      .toHaveText(new RegExp(`^${player}: [0-9]+ points$`));
  }
  await page.getByRole("button", { name: "Deal", exact: true }).click();
  await expect(hand).toHaveCount(6);
  await expect(actions).toHaveCount(0);
  await expect(go).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Play:", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Player: 0 points", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Computer: 0 points", exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
