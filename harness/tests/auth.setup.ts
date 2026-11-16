import { test, expect } from '../lib/fixtures';
import { owner, OWNER_STORAGE } from '../lib/env';

test('the owner signs in through the login page', async ({ page }) => {
  const account = owner();
  await page.goto('/login');
  await page.locator('#login-email').fill(account.email);
  await page.locator('#login-password').fill(account.password);
  await page.locator('form button[type="submit"]').click();
  await page.waitForURL((url) => !url.pathname.startsWith('/login'));
  await expect(page.locator('[data-testid="login-error"]')).toHaveCount(0);
  await page.context().storageState({ path: OWNER_STORAGE });
});
