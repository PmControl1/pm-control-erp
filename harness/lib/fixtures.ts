/**
 * The harness `test`: Playwright's, plus a watchdog on every page.
 *
 * The watchdog listens while a test runs and fails the test, even when its own
 * assertions passed, if the page threw an uncaught error, any /api call came
 * back 5xx, or the app's crash screen is showing at the end. Console errors and
 * 4xx answers are recorded for the report without failing on their own, since
 * a page may legitimately probe an optional endpoint.
 *
 * Every 5xx is recorded with its X-Request-ID, which the server also writes on
 * each log line, so the report can show the server's own traceback for it.
 */
import { test as base, expect, type Page } from '@playwright/test';

export type Finding = { kind: 'pageerror' | 'api5xx' | 'api4xx' | 'console' | 'requestfailed'; detail: string; requestId?: string };

const NOISE = [/ResizeObserver loop/];

function watch(page: Page, findings: Finding[]): void {
  page.on('pageerror', (error) => findings.push({ kind: 'pageerror', detail: `${error.name}: ${error.message}` }));
  page.on('console', (message) => {
    if (message.type() !== 'error') return;
    const text = message.text();
    // The browser repeats every failed fetch as a console line; the response
    // listener already has those, with their status and request ID.
    if (NOISE.some((n) => n.test(text)) || /Failed to load resource/.test(text)) return;
    findings.push({ kind: 'console', detail: text.slice(0, 500) });
  });
  page.on('response', (response) => {
    const url = new URL(response.url());
    if (!url.pathname.startsWith('/api/')) return;
    const status = response.status();
    if (status < 400) return;
    findings.push({
      kind: status >= 500 ? 'api5xx' : 'api4xx',
      detail: `${status} ${response.request().method()} ${url.pathname}`,
      requestId: response.headers()['x-request-id'],
    });
  });
  page.on('requestfailed', (request) => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith('/api/')) return;
    // Navigating away aborts in-flight requests; that is not a failure.
    if (request.failure()?.errorText.includes('ERR_ABORTED')) return;
    findings.push({ kind: 'requestfailed', detail: `${request.method()} ${url.pathname}: ${request.failure()?.errorText}` });
  });
}

export const test = base.extend<{ watchdog: Finding[] }>({
  watchdog: [
    async ({ page }, use, testInfo) => {
      const findings: Finding[] = [];
      watch(page, findings);
      await use(findings);

      if (!page.isClosed() && (await page.locator('[data-testid="error-boundary-fallback"]').count()) > 0) {
        findings.push({ kind: 'pageerror', detail: `The crash screen is showing on ${new URL(page.url()).pathname}` });
      }
      if (findings.length) {
        await testInfo.attach('watchdog', { body: JSON.stringify(findings, null, 2), contentType: 'application/json' });
      }
      const fatal = findings.filter((f) => f.kind === 'pageerror' || f.kind === 'api5xx');
      if (fatal.length) {
        const lines = fatal.map((f) => `  - ${f.detail}${f.requestId ? ` (request ${f.requestId})` : ''}`);
        throw new Error(`The page broke while this test ran:\n${lines.join('\n')}`);
      }
    },
    { auto: true },
  ],
});

export { expect };
