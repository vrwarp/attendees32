import { test as base, expect, Page } from '@playwright/test';

import { PASSWORD, Persona, secondFactor } from './golden';
import { totp } from './totp';

/** Errors the page throws that say nothing about the application. */
const IGNORABLE_PAGE_ERRORS = [/ResizeObserver/];

/**
 * WebKit reports a request cancelled by a navigation as "… due to access
 * control checks." The journeys navigate on purpose while a grid is still
 * fetching — somebody clicking Save before the page has settled does the same
 * thing — so for the application's own host this is the browser narrating our
 * click, not a fault.
 *
 * A genuine cross-origin refusal carries the identical wording, so the host
 * has to match the application under test before this is forgiven.
 */
function isRequestCancelledByNavigation(message: string, baseURL?: string): boolean {
  if (!/due to access control checks/.test(message)) return false;
  const host = baseURL ? new URL(baseURL).host : '';
  return host !== '' && message.includes(host);
}

export const test = base.extend<{
  signIn: (persona: Persona) => Promise<void>;
  pageErrors: string[];
}>({
  page: async ({ page, baseURL }, use) => {
    // Nothing leaves the building. Every library the pages use is served by
    // the application itself (static/vendor/), and a member's browser is meant
    // to talk to the church server alone; so a request to any other host is
    // refused here and fails the test that made it. The suite is the packet
    // capture the design asks for.
    const foreign: string[] = [];
    await page.context().route(
      (url) => !url.href.startsWith(baseURL ?? ''),
      async (route) => {
        foreign.push(route.request().url());
        await route.abort();
      },
    );
    // DevExtreme grows a popup in over 300 ms. A click during that time
    // presses the button where it was and releases it where it is now, and
    // the browser drops the click: one CI run lost "Undo merge" that way.
    // The suite runs with DevExtreme's animations off.
    await page.context().addInitScript(() => {
      document.addEventListener('DOMContentLoaded', () => {
        const dx = (window as any).DevExpress;
        if (dx && dx.fx) dx.fx.off = true;
      });
    });
    await use(page);
    expect(foreign, 'the page reached a host other than the application').toEqual([]);
  },

  pageErrors: async ({ page, baseURL }, use) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await use(errors);
    const fatal = errors.filter(
      (message) =>
        !IGNORABLE_PAGE_ERRORS.some((pattern) => pattern.test(message)) &&
        !isRequestCancelledByNavigation(message, baseURL),
    );
    expect(fatal, 'the page threw JavaScript errors').toEqual([]);
  },

  signIn: async ({ page, pageErrors }, use) => {
    void pageErrors; // collect errors from the first navigation onwards
    await use(async (persona: Persona) => {
      // Signing in as somebody else mid-test has to start from no session:
      // allauth redirects an already-authenticated visitor away from the
      // login page, and there would be no form to fill in.
      await page.context().clearCookies();
      await page.goto('/accounts/login/', { waitUntil: 'domcontentloaded' });
      await page.fill("input[name='login']", persona);
      await page.fill("input[name='password']", PASSWORD);
      await Promise.all([
        page.waitForURL((url) => !url.pathname.startsWith('/accounts/login')),
        page.click("button[type='submit'], input[type='submit']"),
      ]);
      // A persona enrolled with an authenticator app is asked for its code
      // next; the manifest carries the secret the builder enrolled it with.
      if (/\/accounts\/(2fa|mfa)\/authenticate/.test(new URL(page.url()).pathname)) {
        const secret = secondFactor(persona);
        if (!secret) {
          throw new Error(`${persona} was asked for a second factor, and the manifest holds no secret for them`);
        }
        await page.fill("input[name='code']", totp(secret));
        await Promise.all([
          page.waitForURL((url) => !/authenticate/.test(url.pathname)),
          page.click("button[type='submit'], input[type='submit']"),
        ]);
      }
    });
  },
});

export { expect };

/** Navigate without waiting on every last third-party subresource. */
export async function visit(page: Page, path: string): Promise<void> {
  await page.goto(path, { waitUntil: 'domcontentloaded' });
}

/** Wait for a DevExtreme grid inside `container` to have rendered rows. */
export async function waitForGridRows(page: Page, container: string) {
  await page.waitForSelector(`${container} .dx-datagrid`);
  await page.waitForSelector(`${container} .dx-data-row`);
  return page.locator(`${container} .dx-data-row`);
}
