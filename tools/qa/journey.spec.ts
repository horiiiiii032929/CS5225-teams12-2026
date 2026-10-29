import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mkdirSync, writeFileSync } from 'node:fs';

const evidenceDir = '.qa-artifacts/evidence';
const evidence: object[] = [];

async function audit(page: Page, state: string) {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();
  // Store only rule IDs/impact/selectors, never raw HTML or member capabilities.
  const violations = results.violations.map((item) => ({
    id: item.id,
    impact: item.impact,
    targets: item.nodes.map((node) => node.target),
  }));
  evidence.push({
    scenario: test.info().title,
    state,
    viewport: page.viewportSize(),
    violations,
  });
  expect(violations, `Accessibility violations in ${state}`).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    `Page overflow in ${state}`,
  ).toBe(true);
}
async function capture(page: Page, name: string) {
  mkdirSync(evidenceDir, { recursive: true });
  await page.screenshot({
    path: `${evidenceDir}/${name}.png`,
    fullPage: true,
    mask: [page.locator('#invite-link')],
  });
}
async function savePreferences(page: Page, budget = '1800') {
  await page.getByRole('button', { name: 'Add your preferences' }).click();
  await page.getByRole('button', { name: 'Save my preferences' }).click();
  await expect(
    page.getByLabel('Where do you travel to most days?'),
  ).toBeFocused();
  await page.getByLabel('Where do you travel to most days?').fill('Kent Ridge');
  await page
    .getByRole('button', { name: /Kent Ridge MRT Station · Kent Ridge/ })
    .click();
  await page.getByLabel('Your monthly rent budget (SGD)').fill(budget);
  await page.getByLabel('Longest comfortable commute (minutes)').fill('60');
  await audit(page, 'member-input');
  await capture(page, 'member-input');
  await page.getByRole('button', { name: 'Save my preferences' }).focus();
  await page.keyboard.press('Enter');
  await expect(
    page.getByRole('button', { name: 'Edit your preferences' }),
  ).toBeVisible();
}

test.afterAll(() => {
  mkdirSync(evidenceDir, { recursive: true });
  writeFileSync(
    `${evidenceDir}/audit.json`,
    JSON.stringify(
      {
        generatedAt: new Date().toISOString(),
        mode: 'local_synthetic',
        limitations: [
          'Moto persistence, synthetic place/rent and injected conditional route completions',
          'No live OneMap/worker/deployed acceptance or participant study',
          'Axe plus keyboard checks are not a full screen-reader audit',
        ],
        checks: evidence,
      },
      null,
      2,
    ),
  );
});

for (const size of [2, 5]) {
  test(`${size}-member sharing, editing, results and mobile accessibility`, async ({
    browser,
    baseURL,
  }) => {
    const contexts = await Promise.all(
      Array.from({ length: size }, () =>
        browser.newContext({ viewport: { width: 390, height: 844 } }),
      ),
    );
    const pages = await Promise.all(
      contexts.map((context) => context.newPage()),
    );
    const errors: string[] = [];
    pages.forEach((page) =>
      page.on('pageerror', (error) => errors.push(error.name)),
    );
    const owner = pages[0]!;
    await owner.goto(baseURL!);
    await owner
      .getByLabel('Give your group a name')
      .fill(`Synthetic demo ${size}`);
    await owner.getByLabel('Your first name').fill('Alex');
    await owner.getByRole('radio', { name: `${size} people` }).click();
    await audit(owner, 'create');
    await capture(owner, `${size}-create`);
    await owner
      .getByRole('button', { name: 'Create your group', exact: true })
      .focus();
    await owner.keyboard.press('Enter');
    const invitation = await owner.locator('#invite-link').inputValue();
    for (let index = 1; index < size; index++) {
      const page = pages[index]!;
      await page.goto(invitation);
      await page
        .getByLabel('Your first name')
        .fill(['Alex', 'Jamie', 'Sam', 'Dee', 'Fin'][index]!);
      await page
        .getByRole('button', { name: 'Join the group', exact: true })
        .click();
      await expect(
        page.getByRole('button', { name: 'Add your preferences' }),
      ).toBeVisible();
      expect(new URL(page.url()).hash).toBe('');
    }
    for (const page of pages) await savePreferences(page);
    await owner.reload();
    await audit(owner, 'ready-group');
    await owner
      .getByRole('button', { name: 'Find our neighbourhoods' })
      .focus();
    await owner.keyboard.press('Enter');
    await expect(
      owner.getByRole('region', { name: 'Singapore town reference map' }),
    ).toBeVisible({ timeout: 30_000 });
    await expect(
      owner
        .getByRole('region', { name: 'Ranked town comparison' })
        .getByRole('columnheader'),
    ).toHaveCount(4);
    await expect(
      owner
        .getByRole('region', { name: 'Ranked town comparison' })
        .getByRole('rowheader', { name: 'Alex’s commute' }),
    ).toBeVisible();
    await audit(owner, 'results-map-mobile');
    await capture(owner, `${size}-results-mobile`);
    const mapButton = owner.getByRole('button', {
      name: /Show Clementi on map/,
    });
    await mapButton.focus();
    await owner.keyboard.press('Space');
    await expect(mapButton).toHaveAttribute('aria-pressed', 'true');
    await owner.keyboard.press('Tab');
    await expect(owner.locator(':focus')).toHaveAttribute(
      'class',
      /town-map-pin/,
    );
    const comparison = owner.getByRole('region', {
      name: 'Ranked town comparison',
    });
    await comparison.focus();
    await owner.keyboard.press('ArrowRight');
    await expect
      .poll(() => comparison.evaluate((element) => element.scrollLeft))
      .toBeGreaterThan(0);
    await owner.setViewportSize({ width: 1280, height: 900 });
    await audit(owner, 'results-map-desktop');
    await capture(owner, `${size}-results-desktop`);
    await owner.getByRole('button', { name: 'Edit your preferences' }).click();
    await owner.getByLabel('Your monthly rent budget (SGD)').fill('1900');
    await owner.getByRole('button', { name: 'Save my preferences' }).click();
    await expect(owner.getByText('Your group has changed')).toBeVisible();
    await expect(
      owner.getByRole('region', { name: 'Singapore town reference map' }),
    ).toHaveCount(0);
    await pages[1]!.reload();
    await expect(pages[1]!.getByText(/S\$1,900\/month/)).toBeVisible();
    await owner.reload();
    await owner.getByRole('button', { name: 'Edit your preferences' }).click();
    await expect(
      owner.getByLabel('Your monthly rent budget (SGD)'),
    ).toHaveValue('1900');
    await owner.getByRole('button', { name: 'Cancel', exact: true }).click();
    await audit(owner, 'stale-group');
    expect(errors).toEqual([]);
    await Promise.all(contexts.map((context) => context.close()));
  });
}
