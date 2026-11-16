/**
 * Every sample file through the upload path the Documents page would use for
 * it, then a check of what the app made of it:
 *
 *   documents  stored under the name it was uploaded with, and downloads back
 *              byte for byte
 *   BIM models processing finishes and the model has elements
 *   drawings   parsing finishes and the original downloads back byte for byte
 *   photos     a photo record exists for it
 *
 * Files meant to be refused must be refused with a message; no file may ever
 * get a server error. One synthetic project holds every upload.
 */
import * as fs from 'node:fs';
import { test, expect } from '../lib/fixtures';
import { bearer, signIn } from '../lib/api';
import { ensureConverter } from '../lib/converters';
import { owner } from '../lib/env';
import { allSamples, folderFor, TIER, type Sample } from '../lib/samples';
import { createProject, downloadDocument, settle, sha256Of, upload, type Uploaded } from '../lib/upload';
import type { APIRequestContext } from '@playwright/test';

const FOLDER_LABEL = { bim_model: 'BIM models', dwg_drawing: 'DWG drawings', photo: 'Photos', document: 'Documents' } as const;
const mb = (n: number) => `${(n / 1e6).toFixed(n < 1e6 ? 2 : 1)} MB`;

function why(up: Uploaded): string {
  const d = up.body.detail;
  if (typeof d === 'string') return d;
  if (d) return JSON.stringify(d);
  return typeof up.body.message === 'string' ? up.body.message : '';
}

let token = '';
let projectId = '';

test.beforeAll(async ({ request }) => {
  token = await signIn(request, owner().email, owner().password);
  projectId = await createProject(request, token, `Файлове (${TIER}) ${new Date().toISOString().slice(0, 16)}`);
});

async function checkDocument(request: APIRequestContext, s: Sample, up: Uploaded) {
  const id = String(up.body.id ?? '');
  expect(id, `the upload answered without a document id: ${JSON.stringify(up.body)}`).not.toBe('');
  const stored = (await (await request.get(`/api/v1/documents/${id}`, { headers: bearer(token) })).json()) as {
    name: string;
    file_size: number;
    category: string;
  };
  test.info().annotations.push({ type: 'stored as', description: `category ${stored.category}` });
  expect(stored.name, 'the document should keep the name it was uploaded with').toBe(s.name);
  expect(stored.file_size, 'stored size').toBe(s.bytes);
  const back = await downloadDocument(request, token, id);
  expect(back.length, 'downloaded size').toBe(s.bytes);
  expect(sha256Of(back), 'the downloaded file must be the uploaded file, byte for byte').toBe(s.sha256);
}

async function checkModel(request: APIRequestContext, s: Sample, up: Uploaded) {
  const modelId = String(up.body.model_id ?? '');
  expect(modelId, `the upload answered without a model id: ${JSON.stringify(up.body)}`).not.toBe('');
  const { last, waitedMs, settled } = await settle(
    async () =>
      (await (await request.get(`/api/v1/bim_hub/${modelId}`, { headers: bearer(token) })).json()) as {
        status: string;
        element_count?: number;
        error_message?: string | null;
      },
    { busy: ['processing', 'pending', 'converting'], timeoutMs: (TIER === 'nightly' ? 20 : 6) * 60_000 },
  );
  test.info().annotations.push({ type: 'processing', description: `${last.status} after ${Math.round(waitedMs / 1000)} s, ${last.element_count ?? 0} elements` });
  expect(settled, `the model is still "${last.status}" after ${Math.round(waitedMs / 1000)} s`).toBe(true);
  if (s.outcome === 'clear' && last.status !== 'ready') {
    expect(last.error_message ?? '', `the model ended "${last.status}" without saying why`).not.toBe('');
    return;
  }
  // "degraded" is the app's own verdict for a model whose elements loaded but
  // whose quantities could not be read: usable, and it says why.
  if (last.status === 'degraded') {
    expect(last.error_message ?? '', 'a degraded model must say what is missing').not.toBe('');
    test.info().annotations.push({ type: 'degraded', description: last.error_message ?? '' });
  } else {
    expect(last.status, `the model ended "${last.status}": ${last.error_message ?? 'no message'}`).toBe('ready');
  }
  expect(last.element_count ?? 0, 'a real model should have elements').toBeGreaterThan(0);
}

async function checkDrawing(request: APIRequestContext, s: Sample, up: Uploaded) {
  const id = String(up.body.id ?? '');
  expect(id, `the upload answered without a drawing id: ${JSON.stringify(up.body)}`).not.toBe('');
  const { last, waitedMs, settled } = await settle(
    async () =>
      (await (await request.get(`/api/v1/dwg_takeoff/drawings/${id}`, { headers: bearer(token) })).json()) as {
        status: string;
        error_message?: string | null;
      },
    { busy: ['uploaded', 'processing'], timeoutMs: 6 * 60_000 },
  );
  test.info().annotations.push({ type: 'processing', description: `${last.status} after ${Math.round(waitedMs / 1000)} s` });
  expect(settled, `the drawing is still "${last.status}" after ${Math.round(waitedMs / 1000)} s`).toBe(true);
  if (s.expect === 'either' || s.outcome === 'clear') {
    if (last.status !== 'ready') expect(last.error_message ?? '', `the drawing ended "${last.status}" without saying why`).not.toBe('');
    return;
  }
  expect(last.status, `the drawing ended "${last.status}": ${last.error_message ?? 'no message'}`).toBe('ready');
  const back = await request.get(`/api/v1/dwg_takeoff/drawings/${id}/download/`, { headers: bearer(token) });
  expect(back.status(), 'downloading the drawing').toBe(200);
  expect(sha256Of(await back.body()), 'the downloaded drawing must be the uploaded file, byte for byte').toBe(s.sha256);
}

async function checkPhoto(s: Sample, up: Uploaded) {
  expect(String(up.body.id ?? ''), `the upload answered without a photo id: ${JSON.stringify(up.body)}`).not.toBe('');
  expect(up.body.filename, 'the photo should keep its file name').toBe(s.name);
}

test.describe('every file type through its upload path', () => {
  for (const s of allSamples().filter((x) => !x.id.startsWith('batch-'))) {
    const folder = folderFor(s);
    test(`${s.kind.toUpperCase()} "${s.name}" (${mb(s.bytes)}) → ${FOLDER_LABEL[folder]} [${s.id}]`, async ({ request }) => {
      test.setTimeout((s.bytes > 50e6 || TIER === 'nightly' ? 30 : 10) * 60_000);
      test.info().annotations.push({ type: 'sample', description: `${s.id}${s.notes ? ` — ${s.notes}` : ''}${s.license ? ` (${s.license})` : ''}` });
      if (s.kind === 'rvt') await ensureConverter(request, token, 'rvt');
      if (s.kind === 'dwg') await ensureConverter(request, token, 'dwg');

      const up = await upload(request, token, projectId, s, folder);
      if (up.throttled) test.info().annotations.push({ type: 'throttled', description: `"too many uploads" ${up.throttled}× before it went through` });
      expect(up.status, `server error from ${up.route}: ${why(up) || JSON.stringify(up.body)}`).toBeLessThan(500);

      if (s.expect === 'rejected' || (s.expect === 'either' && up.status >= 400)) {
        expect(up.status, `this file should have been refused, but ${up.route} accepted it`).toBeGreaterThanOrEqual(400);
        expect(why(up), 'a refusal must tell the user why').not.toBe('');
        test.info().annotations.push({ type: 'refused', description: `${up.status}: ${why(up)}` });
        return;
      }
      expect(up.status, `${up.route} refused it: ${why(up)}`).toBeLessThan(300);

      if (folder === 'bim_model') await checkModel(request, s, up);
      else if (folder === 'dwg_drawing') await checkDrawing(request, s, up);
      else if (folder === 'photo') await checkPhoto(s, up);
      else await checkDocument(request, s, up);
    });
  }
});

test('two different files with the same name both survive', async ({ request }) => {
  const [a, b] = ['duplicate-a', 'duplicate-b'].map((id) => allSamples().find((s) => s.id === id)!);
  const first = await upload(request, token, projectId, a!, 'document');
  const second = await upload(request, token, projectId, b!, 'document');
  expect(first.status).toBeLessThan(300);
  expect(second.status).toBeLessThan(300);
  expect(second.body.id, 'the second upload must be a new document, not an overwrite').not.toBe(first.body.id);
  expect(sha256Of(await downloadDocument(request, token, String(first.body.id))), 'the first file must be unchanged').toBe(a!.sha256);
  expect(sha256Of(await downloadDocument(request, token, String(second.body.id)))).toBe(b!.sha256);
});

test('40 files sent at once, as a dropped folder sends them, all arrive', async ({ request }) => {
  test.setTimeout(5 * 60_000);
  const batch = allSamples().filter((s) => s.id.startsWith('batch-'));
  expect(batch).toHaveLength(40);
  const fresh = await createProject(request, token, `Партида 40 файла ${Date.now()}`);
  // The Documents page starts every upload of a drop at the same moment.
  const results = await Promise.all(
    batch.map(async (s) => {
      const r = await request.post(`/api/v1/documents/upload/?project_id=${fresh}&category=other`, {
        headers: bearer(token),
        multipart: { file: { name: s.name, mimeType: 'application/pdf', buffer: fs.readFileSync(s.path) } },
      });
      return { name: s.name, status: r.status(), detail: r.ok() ? '' : (await r.text()).slice(0, 200) };
    }),
  );
  const refused = results.filter((r) => r.status >= 300);
  expect(
    refused,
    `${refused.length} of 40 were not stored:\n${refused.map((r) => `  ${r.name}: ${r.status} ${r.detail}`).join('\n')}`,
  ).toHaveLength(0);
  const list = (await (await request.get(`/api/v1/documents/?project_id=${fresh}&limit=500`, { headers: bearer(token) })).json()) as {
    items?: unknown[];
    total?: number;
  };
  expect(list.total ?? list.items?.length, 'the project should list all 40').toBe(40);
});
