/**
 * The test stack itself: the app behind its proxy, sign-in, email and AI.
 * If one of these fails, every later test's result means little.
 */
import { test, expect } from '../lib/fixtures';
import { bearer, signIn } from '../lib/api';
import { AI_URL, APP_URL, owner, syntheticEmail } from '../lib/env';
import { linkIn, waitForEmail } from '../lib/mailpit';

test('the app is healthy behind the proxy and serves the interface', async ({ request }) => {
  const health = await request.get('/api/health');
  expect(health.status()).toBe(200);
  expect(await health.json()).toMatchObject({ status: 'healthy', database: 'ok' });

  const home = await request.get('/');
  expect(home.headers()['content-type']).toContain('text/html');
});

test('the signed-in owner lands in the app, not on the login page', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  await expect(page).not.toHaveURL(/\/login/);
});

test.describe('signed out', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('a new colleague resets their password from the email and signs in', async ({ page, request }) => {
    const token = await signIn(request, owner().email, owner().password);
    const email = syntheticEmail('colleague');
    const created = await request.post('/api/v1/users/', {
      headers: bearer(token),
      data: { email, password: `Start1!${Date.now()}xyz`, full_name: 'Колега Тестов', role: 'editor' },
    });
    expect(created.status(), await created.text()).toBe(201);

    const forgot = await request.post('/api/v1/users/auth/forgot-password/', { data: { email } });
    expect(forgot.status(), await forgot.text()).toBe(200);

    const resetLink = linkIn(await waitForEmail(email), '/auth/reset');
    expect(new URL(resetLink).origin, 'the link must point at this installation').toBe(new URL(APP_URL).origin);

    const newPassword = `Nova1!${Date.now()}abc`;
    await page.goto(resetLink);
    const fields = page.locator('input[autocomplete="new-password"]');
    await expect(fields).toHaveCount(2);
    await fields.nth(0).fill(newPassword);
    await fields.nth(1).fill(newPassword);
    const [reset] = await Promise.all([
      page.waitForResponse((r) => r.url().includes('/api/v1/users/auth/reset-password/')),
      page.locator('form button[type="submit"]').click(),
    ]);
    expect(reset.status(), await reset.text()).toBe(200);

    await page.goto('/login');
    await page.locator('#login-email').fill(email);
    await page.locator('#login-password').fill(newPassword);
    await page.locator('form button[type="submit"]').click();
    await page.waitForURL((url) => !url.pathname.startsWith('/login'));
  });
});

test('the workspace AI answers through the stand-in', async ({ request }) => {
  await fetch(`${AI_URL}/_harness/requests`, { method: 'DELETE' });
  const token = await signIn(request, owner().email, owner().password);

  const status = await request.get('/api/v1/ai/workspace/', { headers: bearer(token) });
  expect(await status.json()).toMatchObject({ configured: true, can_manage: true, provider: 'deepseek' });

  const probe = await request.post('/api/v1/ai/workspace/test/', { headers: bearer(token) });
  expect(probe.status(), await probe.text()).toBe(200);
  expect(await probe.json()).toMatchObject({ success: true });

  const seen = (await (await fetch(`${AI_URL}/_harness/requests`)).json()) as Array<{
    authorization: boolean;
    body: { messages: Array<{ content: string }> };
  }>;
  expect(seen.length, 'the app should have called the stand-in AI').toBeGreaterThan(0);
  expect(seen.at(-1)?.authorization, 'the saved key should be sent').toBe(true);
});
