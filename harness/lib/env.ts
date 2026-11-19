import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

/** Where the test stack listens. stack.sh uses the same defaults. */
export const APP_URL = `http://localhost:${process.env.HARNESS_PORT ?? '18080'}`;
export const MAIL_URL = `http://localhost:${process.env.HARNESS_MAIL_PORT ?? '18025'}`;
export const AI_URL = `http://localhost:${process.env.HARNESS_AI_PORT ?? '18001'}`;

export const HARNESS_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const STATE_DIR = process.env.HARNESS_STATE_DIR ?? path.join(HARNESS_DIR, '.state');
export const RESULTS_DIR = path.join(HARNESS_DIR, 'results');
export const OWNER_STORAGE = path.join(RESULTS_DIR, '.auth', 'owner.json');

export type Account = { email: string; password: string; id: string };

/** The firm's owner, created by stack.sh when the stack came up. */
export function owner(): Account {
  const file = path.join(STATE_DIR, 'owner.json');
  if (!fs.existsSync(file)) {
    throw new Error(`No test stack found (${file} is missing). Start one with: bash harness/stack/stack.sh up`);
  }
  return JSON.parse(fs.readFileSync(file, 'utf8')) as Account;
}

/**
 * Invented mail domain for every harness account. Not a reserved name such as
 * example.com: the app refuses to send to those (core/demo_accounts.py), so a
 * password reset to one would never reach Mailpit. Mail never leaves the test
 * stack, which sends everything to Mailpit.
 */
export const MAIL_DOMAIN = 'pmcontrol-harness.eu';

/** A unique, obviously synthetic email address. */
export function syntheticEmail(label: string): string {
  return `${label}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}@${MAIL_DOMAIN}`;
}
