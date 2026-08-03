import { defineConfig, devices } from '@playwright/test';

/**
 * The browser end-to-end suite.
 *
 * It drives a running attendees32 against the golden congregation — 350 people,
 * their families, statuses and eight weeks of attendance. Bring both up first:
 *
 *   docker compose -f local.yml up -d
 *   docker compose -f local.yml run --rm django python manage.py migrate
 *   docker compose -f local.yml run --rm django python manage.py load_golden_data \
 *     --seed --force --manifest e2e/golden-manifest.json
 *   npm run test:e2e
 *
 * The manifest is how these specs know which UUID belongs to Grace Chen; it is
 * written by the same command that loads the data, so the two cannot drift.
 */
export default defineConfig({
  testDir: './e2e',
  // The golden congregation is shared, committed state on one server: running
  // specs in parallel would have them reading each other's navigation.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 90_000,
  expect: { timeout: 25_000 },
  reporter: process.env.CI
    ? [['list'], ['html', { open: 'never' }], ['github']]
    : [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: process.env.ATTENDEES_BASE_URL ?? 'http://localhost:8008',
    viewport: { width: 1440, height: 1000 },
    navigationTimeout: 45_000,
    actionTimeout: 25_000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    // WebKit is not a formality: it is the engine that finds the date-input,
    // flexbox and Intl differences Chromium forgives.
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
  ],
});
