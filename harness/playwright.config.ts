import { defineConfig, devices } from '@playwright/test';
import { APP_URL, OWNER_STORAGE } from './lib/env';

const viewport = { width: 1440, height: 900 };

/**
 * The harness runs against a test stack that is already up
 * (bash harness/stack/stack.sh up). It never starts or stops one itself.
 *
 *   setup     signs the owner in through the real login page, once
 *   chromium  every other test, already signed in as the owner
 */
export default defineConfig({
  testDir: './tests',
  outputDir: 'results/artifacts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [
    ['list'],
    ['html', { outputFolder: 'results/html', open: 'never' }],
    ['json', { outputFile: 'results/results.json' }],
  ],
  use: {
    baseURL: APP_URL,
    locale: 'bg-BG',
    timezoneId: 'Europe/Sofia',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  projects: [
    { name: 'setup', testMatch: /.*\.setup\.ts/, use: { ...devices['Desktop Chrome'], viewport } },
    {
      name: 'chromium',
      testIgnore: /.*\.setup\.ts/,
      dependencies: ['setup'],
      use: { ...devices['Desktop Chrome'], viewport, storageState: OWNER_STORAGE },
    },
  ],
});
