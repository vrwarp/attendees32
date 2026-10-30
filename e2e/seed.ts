import { expect, Page } from '@playwright/test';

import { totp } from './totp';

/**
 * Sign in as `jack`, the superuser of `fixtures/ci_seed.json`, for the specs
 * written against that seed (the `ci-seed` project).
 *
 * A superuser must have a second factor, so the CI jobs enrol jack with an
 * authenticator app and hand its secret over in `C_TOTP_SECRET`; the password
 * is `C_PASSWORD`. Both are set through the DOM or typed as a code, never
 * written into Playwright's reports.
 */
export async function signInAsJack(page: Page): Promise<void> {
  const password = process.env.C_PASSWORD || 'your_password_for_superuser_in_seed';
  await page.goto('/accounts/login/');
  await page.fill('input[name="login"]', 'jack');
  await page.locator('input[name="password"]').evaluate((el, value) => {
    (el as HTMLInputElement).value = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }, password);
  await Promise.all([
    page.waitForURL((url) => !url.pathname.startsWith('/accounts/login')),
    page.click('button[type="submit"]'),
  ]);

  const path = new URL(page.url()).pathname;
  if (/\/accounts\/(2fa|mfa)\/authenticate/.test(path)) {
    const secret = process.env.C_TOTP_SECRET;
    if (!secret) {
      throw new Error(
        'jack has an authenticator app; set C_TOTP_SECRET to the base32 secret it was enrolled with',
      );
    }
    await page.fill('input[name="code"]', totp(secret));
    await Promise.all([
      page.waitForURL((url) => !/authenticate/.test(url.pathname)),
      page.click('button[type="submit"]'),
    ]);
  } else if (path.startsWith('/accounts/2fa/')) {
    throw new Error(
      'jack is a superuser without a second factor, so the application sends him to enrol one; ' +
        'the seed specs need him enrolled first (see "How to run test" in the README)',
    );
  }

  await expect(page).toHaveURL(/\/users\/jack\//);
  await expect(page.locator('a[href="/accounts/logout/"]')).toBeVisible({ timeout: 15000 });
}
