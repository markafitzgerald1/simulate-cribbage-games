/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. */

import { expect, Page, test } from "@playwright/test";

const HAND_COUNT = 10;

const rankCount = (action: string): number => {
  const rank = action.slice(0, -1);
  return rank === "A" ? 1 : /^[TJQK]$/.test(rank) ? 10 : Number(rank);
};

// Read in one evaluate so an opponent play cannot land between the two values.
const readPlay = (page: Page) =>
  page.evaluate(() => ({
    count: document.querySelector("h3")?.textContent ?? "",
    sequences: [
      ...document.querySelectorAll('[data-testid="play-history"] ul'),
    ].map((sequence) =>
      [...sequence.querySelectorAll("li")].map((li) => li.textContent ?? "")
    ),
  }));

const expectConsistentPlay = async (page: Page): Promise<void> => {
  const { count, sequences } = await readPlay(page);
  const totals = sequences.map((sequence) =>
    sequence
      .filter((action) => action !== "Go")
      .reduce((total, action) => total + rankCount(action), 0)
  );
  totals.forEach((total) => expect(total).toBeLessThanOrEqual(31));
  expect(count).toBe(`Play count is ${totals.at(-1) ?? 0}`);
};

test(`discard and finish ${HAND_COUNT} random hands without browser errors`, async ({
  page,
}) => {
  test.setTimeout(60_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });

  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Play Cribbage" })
  ).toBeVisible();
  const hand = page.getByTestId("player-hand").getByRole("listitem");
  const actions = page.getByTestId("play-history").getByRole("listitem");
  const playedCards = actions.filter({ hasNotText: /^Go$/ });
  const go = page.getByRole("button", { name: "Say 'Go'", exact: true });

  for (let handNumber = 1; handNumber <= HAND_COUNT; handNumber++) {
    await expect(hand).toHaveCount(6);
    await expect(actions).toHaveCount(0);
    await expect(go).toHaveCount(0);
    await expect(
      page.getByRole("heading", { name: "Play:", exact: true })
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Player: 0 points", exact: true })
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Computer: 0 points", exact: true })
    ).toBeVisible();
    console.log(`hand ${handNumber}: ${await hand.allTextContents()}`);

    await hand.first().click();
    await expect(hand).toHaveCount(5);
    await hand.first().click();
    await expect(hand).toHaveCount(4);

    // Four plays plus at most two Go actions per count reset fit well below 24.
    for (let turn = 0; turn < 24; turn++) {
      await expectConsistentPlay(page);
      if ((await playedCards.count()) === 8) break;

      const playable = hand.and(page.locator('[aria-disabled="false"]'));
      if ((await playable.count()) > 0) {
        const remaining = await hand.count();
        await playable.first().click();
        await expect(hand).toHaveCount(remaining - 1);
      } else {
        await expect(go).toBeEnabled();
        const previousActions = await actions.count();
        await go.click();
        await expect.poll(() => actions.count()).toBeGreaterThan(
          previousActions
        );
      }
    }

    await expect(playedCards).toHaveCount(8);
    await expectConsistentPlay(page);
    await expect(hand).toHaveCount(0);
    await expect(go).toBeDisabled();
    for (const player of ["Player", "Computer"]) {
      await expect(
        page.getByRole("heading", { name: new RegExp(`^${player}:`) })
      ).toHaveText(new RegExp(`^${player}: [0-9]+ points$`));
    }
    await page.getByRole("button", { name: "Deal", exact: true }).click();
  }

  await expect(hand).toHaveCount(6);
  expect(errors).toEqual([]);
});
