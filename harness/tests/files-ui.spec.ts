/**
 * The Documents page itself: files chosen in its upload dialog, the way a
 * person does it, with the browser making every request the app makes.
 *
 * The folder a file is uploaded into decides where it goes (useFileUpload.ts):
 * BIM models to BIM Hub, DWG drawings to DWG takeoff, everything else to
 * documents. A new project shows no folders, only one upload button, which
 * uploads with no folder chosen; a folder opens from the page's ?kind= link.
 */
import { test, expect } from '../lib/fixtures';
import { bearer, signIn } from '../lib/api';
import { ensureConverter } from '../lib/converters';
import { owner } from '../lib/env';
import { closeFirstRunWizard } from '../lib/firstRun';
import { allSamples, sample, type Folder } from '../lib/samples';
import { createProject, settle, UPLOAD_WINDOW_MS, waitForFreshUploadWindow } from '../lib/upload';
import type { Page, Response } from '@playwright/test';

const UPLOAD = /^(Качване на файлове|Upload files)$/;

let token = '';
test.beforeAll(async ({ request }) => {
  token = await signIn(request, owner().email, owner().password);
});

// Each test is one person's action: start it with a fresh upload minute, not
// one the earlier tests (same owner) have already used up.
test.beforeEach(async () => {
  test.setTimeout(test.info().timeout + UPLOAD_WINDOW_MS);
  await waitForFreshUploadWindow();
});

/**
 * Open a project's Documents page, in one folder or (null) with none chosen,
 * and its upload dialog.
 */
async function openUpload(page: Page, projectId: string, folder: Exclude<Folder, 'document'> | null) {
  await page.goto(folder ? `/projects/${projectId}/files?kind=${folder}` : `/projects/${projectId}/files`);
  await closeFirstRunWizard(page, 3_000);
  const button = page.getByRole('main').getByRole('button', { name: UPLOAD }).first();
  try {
    await button.click({ timeout: 20_000 });
  } catch {
    // Say what is on the page instead, so the report shows why.
    const headings = await page.getByRole('heading').allInnerTexts().catch(() => [] as string[]);
    const main = await page.locator('main').first().ariaSnapshot({ timeout: 5_000 }).catch(() => '(no main region)');
    throw new Error(
      `No upload button on ${new URL(page.url()).pathname}${new URL(page.url()).search}.\n` +
        `Headings: ${headings.map((h) => h.trim()).filter(Boolean).join(' | ') || '(none)'}\n` +
        `Main region:\n${main.split('\n').slice(0, 60).join('\n')}`,
    );
  }
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  return dialog.locator('input[type="file"]');
}

/** Collect the answers to uploads the page sends to `route`. */
function answersTo(page: Page, route: string): Response[] {
  const seen: Response[] = [];
  page.on('response', (r) => {
    if (r.request().method() === 'POST' && new URL(r.url()).pathname.startsWith(route)) seen.push(r);
  });
  return seen;
}

async function describe(responses: Response[]): Promise<string> {
  const lines = await Promise.all(
    responses.filter((r) => r.status() >= 300).map(async (r) => `  ${r.status()} ${(await r.text().catch(() => '')).slice(0, 160)}`),
  );
  return lines.join('\n');
}

test('40 files chosen at once on a new project\'s Documents page all arrive', async ({ page, request }) => {
  test.setTimeout(5 * 60_000);
  const projectId = await createProject(request, token, `Партида през интерфейса ${Date.now()}`);
  const batch = allSamples().filter((s) => s.id.startsWith('batch-'));
  const answers = answersTo(page, '/api/v1/documents/upload/');

  const input = await openUpload(page, projectId, null);
  await input.setInputFiles(batch.map((s) => s.path));

  await expect.poll(() => answers.length, { timeout: 3 * 60_000, message: 'waiting for the page to send all 40' }).toBe(40);
  const failed = answers.filter((r) => r.status() >= 300);
  expect(failed, `${failed.length} of 40 uploads failed:\n${await describe(answers)}`).toHaveLength(0);

  const list = (await (await request.get(`/api/v1/documents/?project_id=${projectId}&limit=500`, { headers: bearer(token) })).json()) as {
    total: number;
  };
  expect(list.total, 'the project should list all 40').toBe(40);
});

test('an IFC uploaded into the BIM models folder becomes a model with elements', async ({ page, request }) => {
  test.setTimeout(10 * 60_000);
  const projectId = await createProject(request, token, `IFC през интерфейса ${Date.now()}`);
  const ifc = sample('ifc4-building-architecture');
  const answers = answersTo(page, '/api/v1/bim_hub/upload-cad/');

  const input = await openUpload(page, projectId, 'bim_model');
  await input.setInputFiles(ifc.path);

  await expect.poll(() => answers.length, { timeout: 2 * 60_000 }).toBe(1);
  expect(answers[0]!.status(), await describe(answers)).toBeLessThan(300);
  const modelId = String(((await answers[0]!.json()) as { model_id?: string }).model_id);
  const { last, settled } = await settle(
    async () => (await (await request.get(`/api/v1/bim_hub/${modelId}`, { headers: bearer(token) })).json()) as { status: string; element_count: number; error_message?: string },
    { busy: ['processing', 'pending', 'converting'], timeoutMs: 6 * 60_000 },
  );
  expect(settled, `still "${last.status}"`).toBe(true);
  expect(last.status, last.error_message ?? '').toBe('ready');
  expect(last.element_count).toBeGreaterThan(0);
});

test('a DWG uploaded into the DWG drawings folder is parsed', async ({ page, request }) => {
  test.setTimeout(20 * 60_000);
  await ensureConverter(request, token, 'dwg');
  const projectId = await createProject(request, token, `DWG през интерфейса ${Date.now()}`);
  const dwg = sample('dwg-2018');
  const answers = answersTo(page, '/api/v1/dwg_takeoff/drawings/upload/');

  const input = await openUpload(page, projectId, 'dwg_drawing');
  await input.setInputFiles(dwg.path);

  await expect.poll(() => answers.length, { timeout: 2 * 60_000 }).toBe(1);
  expect(answers[0]!.status(), await describe(answers)).toBeLessThan(300);
  const id = String(((await answers[0]!.json()) as { id?: string }).id);
  const { last, settled } = await settle(
    async () => (await (await request.get(`/api/v1/dwg_takeoff/drawings/${id}`, { headers: bearer(token) })).json()) as { status: string; error_message?: string },
    { busy: ['uploaded', 'processing'], timeoutMs: 6 * 60_000 },
  );
  expect(settled, `still "${last.status}"`).toBe(true);
  expect(last.status, last.error_message ?? '').toBe('ready');
});

test('a PDF put into the BIM models folder is explained on screen, not silently lost', async ({ page, request }) => {
  test.setTimeout(3 * 60_000);
  const projectId = await createProject(request, token, `Грешна папка ${Date.now()}`);
  const pdf = sample('protocol-pdf');
  const answers = answersTo(page, '/api/v1/');

  const input = await openUpload(page, projectId, 'bim_model');
  await input.setInputFiles(pdf.path);

  await expect.poll(() => answers.length, { timeout: 60_000 }).toBeGreaterThan(0);
  const answer = answers[0]!;
  expect(answer.status(), 'no server error').toBeLessThan(500);
  if (answer.status() < 300) {
    test.info().annotations.push({ type: 'outcome', description: `accepted by ${new URL(answer.url()).pathname}` });
    return;
  }
  const body = (await answer.json().catch(() => ({}))) as { detail?: unknown };
  const detail = typeof body.detail === 'string' ? body.detail : String((body.detail as { message?: string })?.message ?? '');
  expect(detail, 'the refusal should carry a reason').not.toBe('');
  // The reason must reach the person, not only the network tab. The page
  // translates refusal codes, so look at what the upload queue shows for this
  // file rather than for the server's English sentence.
  const row = page
    .locator('div')
    .filter({ has: page.getByText(pdf.name, { exact: true }) })
    .filter({ has: page.locator('.text-semantic-error') })
    .last();
  await expect(row, `the upload queue should list ${pdf.name} as failed`).toBeVisible({ timeout: 15_000 });
  const shown = (await row.locator('.text-semantic-error').last().innerText()).trim();
  test.info().annotations.push({ type: 'shown to the person', description: shown });
  expect(shown, 'the person should see why, not only that it failed').not.toMatch(/^(Failed|Неуспешно|Грешка|)$/i);
});

test('an IFC uploaded on a new project\'s Documents page, with no folder chosen, becomes a model', async ({ page, request }) => {
  test.setTimeout(10 * 60_000);
  // A new project offers one upload button and no folders, so this is what a
  // person new to the app does with a model file.
  const projectId = await createProject(request, token, `IFC без папка ${Date.now()}`);
  const ifc = sample('ifc4-building-architecture');
  const answers = answersTo(page, '/api/v1/');

  const input = await openUpload(page, projectId, null);
  await input.setInputFiles(ifc.path);

  await expect.poll(() => answers.length, { timeout: 2 * 60_000 }).toBeGreaterThan(0);
  const route = new URL(answers[0]!.url()).pathname;
  expect(answers[0]!.status(), await describe(answers)).toBeLessThan(300);
  test.info().annotations.push({ type: 'sent to', description: route });

  let models: unknown[] = [];
  await expect
    .poll(
      async () => {
        const body = (await (await request.get(`/api/v1/bim_hub/?project_id=${projectId}`, { headers: bearer(token) })).json()) as
          | { items?: unknown[] }
          | unknown[];
        models = Array.isArray(body) ? body : (body.items ?? []);
        return models.length;
      },
      { timeout: 2 * 60_000, message: `the IFC went to ${route} and no BIM model was created: it is stored as a plain document` },
    )
    .toBeGreaterThan(0);
});
