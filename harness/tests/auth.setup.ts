import { test, expect } from '../lib/fixtures';
import { owner, OWNER_STORAGE } from '../lib/env';
import { closeFirstRunWizard } from '../lib/firstRun';

test('the owner signs in through the login page', async ({ page }) => {
  const account = owner();
  await page.goto('/login');
  await page.locator('#login-email').fill(account.email);
  await page.locator('#login-password').fill(account.password);
  // Without "remember me" the app keeps the sign-in in this tab's
  // sessionStorage, which a saved browser state cannot carry to the next test.
  await page.getByLabel(/Запомни ме|Remember me/).check();
  await page.locator('form button[type="submit"]').click();
  await page.waitForURL((url) => !url.pathname.startsWith('/login'));
  await expect(page.locator('[data-testid="login-error"]')).toHaveCount(0);
  // A firm's first day: the owner answers the first-run wizard once.
  if (await closeFirstRunWizard(page)) test.info().annotations.push({ type: 'first run', description: 'closed the first-run wizard' });
  await page.context().storageState({ path: OWNER_STORAGE });
});
