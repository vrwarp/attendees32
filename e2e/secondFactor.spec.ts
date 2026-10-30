import { expect, test, visit } from './fixtures';

/**
 * Staff and superusers see other people's records, so a stolen password
 * alone must open nothing: such an account needs an authenticator app or a
 * passkey, and until it has one it gets only the enrolment pages. Members may
 * enrol one; they are not made to (account.spec.ts drives that choice).
 */
test.describe('a second factor for the accounts that see everything', () => {
  test('a superuser signs in with a password and a code from the app', async ({
    page,
    signIn,
  }) => {
    // The golden superuser is enrolled; signIn types the code from the
    // manifest's secret when the second step appears.
    await signIn('golden_superuser');
    await expect(page).not.toHaveURL(/\/accounts\/(2fa|mfa)\//);
    await visit(page, '/admin123/');
    await expect(page.locator('body')).toContainText(/administration/i);
  });

  test('a new officer without one is sent to enrol and can open nothing else', async ({
    page,
    signIn,
  }) => {
    await signIn('golden_new_officer');
    await expect(page).toHaveURL(/\/accounts\/(2fa|mfa)\//);

    // A page of the application comes straight back here, and says why.
    await visit(page, '/persons/attendees/');
    await expect(page).toHaveURL(/\/accounts\/(2fa|mfa)\//);
    await expect(page.locator('body')).toContainText(/second factor/i);

    // The API is refused rather than redirected.
    const response = await page.request.get('/persons/api/datagrid_data_attendees/?take=5');
    expect(response.status()).toBe(403);
    expect(await response.text()).toMatch(/second factor/);

    // Signing out still works, so nobody is stuck.
    await visit(page, '/accounts/logout/');
    await expect(page).not.toHaveURL(/\/accounts\/(2fa|mfa)\//);
  });
});
