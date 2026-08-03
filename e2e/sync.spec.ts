import { expect, test, visit } from './fixtures';

/**
 * The Planning Center report, worked through rather than read.
 *
 * `journeys.spec.ts` settles a field conflict. This is the other half of the
 * screen: narrowing six hundred differences down to the one you mean, and the
 * manual matcher — the only way an unmatched Planning Center person ever
 * acquires an attendee, because the sync suggests and never links.
 *
 * Matching is one-shot, like settling: once Kirby Allen has an attendee he is
 * no longer unmatched. CI builds the congregation fresh for every job; a second
 * local run wants `load_golden_data --force` first.
 */

const TABLE = '#pcosync-divergences';

test.describe('a data admin narrows the report', () => {
  test('filters by kind, and searches by name and field', async ({ page, signIn }) => {
    // Six hundred rows is the normal case after a first sync, so the filters
    // are not a nicety — they are how anybody finds the row they mean.
    await signIn('golden_data_organizer');
    await visit(page, '/pcosync/sync/');

    const table = page.locator(TABLE);
    await expect(table.locator('tbody tr')).not.toHaveCount(0);
    const all = await table.locator('tbody tr').count();

    await page.selectOption('#pcosync-kind', 'unlinked_person');
    await expect
      .poll(async () => table.locator('tbody tr').count(), {
        message: 'filtering by kind changed nothing',
      })
      .toBeLessThan(all);
    await expect(table).toContainText('Kirby Allen');

    await page.selectOption('#pcosync-kind', '');
    await page.fill('#pcosync-search', 'household');
    await expect
      .poll(async () => table.innerText())
      .toMatch(/household/i);

    await page.fill('#pcosync-search', 'nobody-by-this-name');
    await expect(table).toContainText(/nothing open/i);
  });

  test('an ordinary member never reaches the report at all', async ({
    page,
    signIn,
  }) => {
    await signIn('golden_member');
    await visit(page, '/pcosync/sync/');
    await expect(page.locator('body')).toContainText(
      'does not have permissions to visit such route',
    );
  });
});

test.describe('a data admin matches an unknown person by hand', () => {
  test('searches the congregation and links the row', async ({ page, signIn }) => {
    await signIn('golden_data_organizer');
    await visit(page, '/pcosync/sync/');

    const table = page.locator(TABLE);
    await expect(table).toContainText('Kirby Allen');
    const before = await table.locator('tbody tr').count();

    // "Match…" replaces the cell with a search box rather than a modal, so the
    // row you are matching stays on screen beside it.
    await table.locator('[data-link-row]').first().click();
    const search = table.locator('[data-search-for]');
    await expect(search).toBeVisible();

    // It opens with the sync's own suggestions already listed — the run does
    // the guessing, a person does the deciding.
    const candidates = table.locator('[data-results-for] [data-attendee]');
    await expect(candidates.first()).toBeVisible();

    // And a romanised surname typed by hand has to find the Han spelling,
    // which is the whole difficulty of matching this congregation against
    // somebody else's export. (The two-character floor is in
    // ``test_pcosync_api.py``; here the point is that typing searches at all.)
    await search.fill('Tsai');
    await expect(table.locator('[data-results-for]')).toContainText('蔡');

    await candidates.first().click();

    // Linked, so the question is answered and leaves the open report.
    await expect
      .poll(async () => table.locator('tbody tr').count(), {
        message: 'the matched row never left the open list',
      })
      .toBeLessThan(before);
    await expect(table).not.toContainText('Kirby Allen');
  });
});
