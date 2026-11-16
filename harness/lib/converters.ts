/**
 * The DDC converters the owner installs once in Settings > BIM Converters:
 * RVT needs one, DWG needs one, IFC also has a built-in reader. The harness
 * installs them the same way (the install button's API) before the first
 * RVT or DWG upload, so those tests exercise the setup a real firm has.
 */
import { expect, type APIRequestContext } from '@playwright/test';
import { bearer } from './api';

const pending = new Map<string, Promise<void>>();

async function install(request: APIRequestContext, token: string, id: string): Promise<void> {
  const started = await request.post(`/api/v1/takeoff/converters/${id}/install/`, { headers: bearer(token), timeout: 120_000 });
  const body = (await started.json().catch(() => ({}))) as Record<string, unknown>;
  expect(started.status(), `installing the ${id} converter: ${JSON.stringify(body)}`).toBe(200);
  if (body.installed === true) return;
  expect(body.platform_unsupported, `the ${id} converter has no build for this server: ${JSON.stringify(body)}`).not.toBe(true);

  const deadline = Date.now() + 15 * 60_000;
  let last: Record<string, unknown> = {};
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 3000));
    const progress = await request.get(`/api/v1/takeoff/converters/${id}/install-progress/`, { headers: bearer(token) });
    last = (await progress.json().catch(() => ({}))) as Record<string, unknown>;
    if (last.stage === 'done') {
      expect(last.installed ?? true, `the ${id} converter install finished but is not installed: ${JSON.stringify(last)}`).toBeTruthy();
      return;
    }
    if (last.stage === 'error') throw new Error(`Installing the ${id} converter failed: ${JSON.stringify(last)}`);
  }
  throw new Error(`Installing the ${id} converter did not finish in 15 minutes. Last progress: ${JSON.stringify(last)}`);
}

/** Install a converter once per run; later callers wait for the same install. */
export function ensureConverter(request: APIRequestContext, token: string, id: 'rvt' | 'dwg' | 'ifc'): Promise<void> {
  if (!pending.has(id)) {
    const attempt = install(request, token, id);
    // A failed install is retried by the next caller, not cached as failed.
    attempt.catch(() => pending.delete(id));
    pending.set(id, attempt);
  }
  return pending.get(id)!;
}
