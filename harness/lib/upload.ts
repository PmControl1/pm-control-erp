/**
 * Upload a file the way the Documents page does (frontend
 * src/features/file-manager/useFileUpload.ts), then find out what the app made
 * of it. Keep the routing here in step with that file.
 *
 *   BIM model (IFC, RVT)  POST /api/v1/bim_hub/upload-cad/
 *   Drawing (DWG, DXF)    POST /api/v1/dwg_takeoff/drawings/upload/
 *   Photo                 POST /api/v1/documents/photos/upload/
 *   Anything else         POST /api/v1/documents/upload/, or the resumable
 *                         chunked upload from 12 MB (resumableUpload.ts)
 */
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import { expect, type APIRequestContext, type APIResponse } from '@playwright/test';
import { bearer } from './api';
import { folderFor, mimeFor, type Folder, type Sample } from './samples';

export const RESUMABLE_THRESHOLD_BYTES = 12 * 1024 * 1024;
export const RESUMABLE_CHUNK_SIZE = 8 * 1024 * 1024;

export type Uploaded = {
  folder: Folder;
  route: string;
  status: number;
  body: Record<string, unknown> & { detail?: unknown };
  /** How often the server said "too many uploads" before taking it. */
  throttled: number;
};

async function json(response: APIResponse): Promise<Uploaded['body']> {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text.slice(0, 500) };
  }
}

/** Retry on 429 the way a patient person would, and count it. */
async function patiently(send: () => Promise<APIResponse>): Promise<{ response: APIResponse; throttled: number }> {
  let throttled = 0;
  for (;;) {
    const response = await send();
    if (response.status() !== 429 || throttled >= 10) return { response, throttled };
    throttled += 1;
    const wait = Number(response.headers()['retry-after'] ?? '10');
    await new Promise((r) => setTimeout(r, Math.min(Math.max(wait, 1), 65) * 1000));
  }
}

export async function createProject(request: APIRequestContext, token: string, name: string): Promise<string> {
  const response = await request.post('/api/v1/projects/', {
    headers: bearer(token),
    data: { name, description: 'Синтетичен проект на тестовия харнес', locale: 'bg', currency: 'EUR' },
  });
  expect(response.status(), `creating project "${name}": ${await response.text()}`).toBe(201);
  return ((await response.json()) as { id: string }).id;
}

export async function upload(
  request: APIRequestContext,
  token: string,
  projectId: string,
  s: Sample,
  folder: Folder = folderFor(s),
): Promise<Uploaded> {
  const file = { name: s.name, mimeType: mimeFor(s), buffer: fs.readFileSync(s.path) };
  const post = (route: string) =>
    patiently(() => request.post(route, { headers: bearer(token), multipart: { file }, timeout: 15 * 60_000 }));

  let route: string;
  if (folder === 'bim_model') route = `/api/v1/bim_hub/upload-cad/?project_id=${projectId}`;
  else if (folder === 'dwg_drawing') route = `/api/v1/dwg_takeoff/drawings/upload/?project_id=${projectId}`;
  else if (folder === 'photo') route = `/api/v1/documents/photos/upload/?project_id=${projectId}`;
  else if (s.bytes >= RESUMABLE_THRESHOLD_BYTES) return resumable(request, token, projectId, s);
  else route = `/api/v1/documents/upload/?project_id=${projectId}&category=other`;

  const { response, throttled } = await post(route);
  return { folder, route: route.split('?')[0]!, status: response.status(), body: await json(response), throttled };
}

async function resumable(request: APIRequestContext, token: string, projectId: string, s: Sample): Promise<Uploaded> {
  const base = { folder: 'document' as const, route: '/api/v1/resumable-uploads/sessions/' };
  const sha256 = createHash('sha256').update(fs.readFileSync(s.path)).digest('hex');
  const created = await request.post('/api/v1/resumable-uploads/sessions/', {
    headers: bearer(token),
    data: { project_id: projectId, filename: s.name, total_size: s.bytes, chunk_size: RESUMABLE_CHUNK_SIZE, category: 'other', sha256 },
  });
  if (!created.ok()) return { ...base, status: created.status(), body: await json(created), throttled: 0 };
  const session = (await created.json()) as { id: string; chunk_size: number; total_chunks: number };
  const size = session.chunk_size || RESUMABLE_CHUNK_SIZE;
  const fd = fs.openSync(s.path, 'r');
  try {
    for (let i = 0; i < session.total_chunks; i++) {
      const chunk = Buffer.alloc(Math.min(size, s.bytes - i * size));
      fs.readSync(fd, chunk, 0, chunk.length, i * size);
      const put = await request.put(`/api/v1/resumable-uploads/sessions/${session.id}/chunks/${i}/`, {
        headers: { ...bearer(token), 'Content-Type': 'application/octet-stream' },
        data: chunk,
        timeout: 5 * 60_000,
      });
      if (!put.ok()) return { ...base, route: `${base.route}{id}/chunks/${i}/`, status: put.status(), body: await json(put), throttled: 0 };
    }
  } finally {
    fs.closeSync(fd);
  }
  const done = await request.post(`/api/v1/resumable-uploads/sessions/${session.id}/complete/`, {
    headers: bearer(token),
    timeout: 15 * 60_000,
  });
  const body = await json(done);
  // The documents endpoint answers with the document; complete() with its id.
  if (done.ok() && body.document_id) body.id = body.document_id;
  return { ...base, route: `${base.route}{id}/complete/`, status: done.status(), body, throttled: 0 };
}

export function sha256Of(data: Buffer): string {
  return createHash('sha256').update(data).digest('hex');
}

/** The stored document's bytes, as the download button gets them. */
export async function downloadDocument(request: APIRequestContext, token: string, documentId: string): Promise<Buffer> {
  const response = await request.get(`/api/v1/documents/${documentId}/download/`, { headers: bearer(token), timeout: 10 * 60_000 });
  expect(response.status(), `downloading document ${documentId}`).toBe(200);
  return response.body();
}

/** Poll until `read` reports a status outside `busy`, or give up. */
export async function settle<T extends { status?: string }>(
  read: () => Promise<T>,
  { busy = ['processing', 'pending', 'queued', 'converting', 'uploaded'], timeoutMs = 5 * 60_000 } = {},
): Promise<{ last: T; waitedMs: number; settled: boolean }> {
  const started = Date.now();
  let last = await read();
  while (busy.includes(String(last.status)) && Date.now() - started < timeoutMs) {
    await new Promise((r) => setTimeout(r, 3000));
    last = await read();
  }
  return { last, waitedMs: Date.now() - started, settled: !busy.includes(String(last.status)) };
}
