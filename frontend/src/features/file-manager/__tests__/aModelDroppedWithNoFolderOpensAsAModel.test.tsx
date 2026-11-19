// A model or a drawing uploaded with no folder chosen goes where it can be
// opened. On a new project "no folder" is the only choice, and every file used
// to land in documents: an IFC there has no viewer, no elements and no
// quantities. A refusal from that pipeline must still not lose the file, since
// nobody asked for a model, so it is kept as a document, as it always was.
import { type ReactNode } from 'react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { useFileUpload, kindForUnfiledFile } from '../useFileUpload';
import { useUploadQueueStore } from '@/stores/useUploadQueueStore';
import { uploadResumable } from '../resumableUpload';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      String(opts?.defaultValue ?? key).replace(/\{\{(\w+)\}\}/g, (_, k: string) => String(opts?.[k] ?? '')),
  }),
}));
vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: { getState: () => ({ accessToken: 'test-token' }) },
}));
// Ten bytes counts as "large" here, so the resumable path is cheap to reach.
vi.mock('../resumableUpload', () => ({
  RESUMABLE_THRESHOLD_BYTES: 10,
  uploadResumable: vi.fn(async () => undefined),
}));

const PROJECT = 'p-1';
const BIM = `/api/v1/bim_hub/upload-cad/?project_id=${PROJECT}`;
const DWG = `/api/v1/dwg_takeoff/drawings/upload/?project_id=${PROJECT}`;
const DOCS = `/api/v1/documents/upload/?project_id=${PROJECT}&category=other`;

type Answer = { status: number; body?: unknown };
let answers: Record<string, Answer[]>;
const fetchMock = vi.fn(async (url: string) => {
  const queued = answers[url]?.shift() ?? { status: 201, body: {} };
  return new Response(JSON.stringify(queued.body ?? {}), { status: queued.status });
});

const small = (name: string) => new File(['12345'], name);
const large = (name: string) => new File(['0123456789abcdefghij'], name);

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

async function uploadAll(files: File[], kind: Parameters<ReturnType<typeof useFileUpload>['doUpload']>[1]) {
  const { result } = renderHook(() => useFileUpload(PROJECT), { wrapper });
  await act(() => result.current.doUpload(files, kind));
  await waitFor(() =>
    expect(useUploadQueueStore.getState().tasks.every((t) => t.status === 'completed' || t.status === 'error')).toBe(true),
  );
  return useUploadQueueStore.getState().tasks;
}

const sentTo = () => fetchMock.mock.calls.map((c) => c[0]);

beforeEach(() => {
  answers = {};
  fetchMock.mockClear();
  vi.mocked(uploadResumable).mockClear();
  vi.stubGlobal('fetch', fetchMock);
  useUploadQueueStore.setState({ tasks: [] });
});
afterEach(() => vi.unstubAllGlobals());

describe('kindForUnfiledFile', () => {
  it.each([
    ['Модел етаж 1.ifc', 'bim_model'],
    ['СГРАДА.RVT', 'bim_model'],
    ['Ситуация.dwg', 'dwg_drawing'],
    ['разрез А-А.DXF', 'dwg_drawing'],
    ['Протокол.pdf', null],
    ['бележки', null],
    ['архив.ifc.zip', null],
  ])('%s -> %s', (name, kind) => {
    expect(kindForUnfiledFile(name)).toBe(kind);
  });
});

describe('uploading with no folder chosen', () => {
  it('sends models to BIM, drawings to DWG takeoff, and the rest to documents', async () => {
    const tasks = await uploadAll(
      [small('Модел етаж 1.ifc'), small('СГРАДА.RVT'), small('Ситуация.dwg'), small('разрез.dxf'), small('Протокол.pdf'), small('мебел.obj')],
      null,
    );
    expect(sentTo()).toEqual([BIM, BIM, DWG, DWG, DOCS, DOCS]);
    expect(tasks.map((t) => t.status)).toEqual(Array(6).fill('completed'));
  });

  it('keeps a model the BIM pipeline refuses as a document, and says why', async () => {
    answers[BIM] = [{ status: 400, body: { detail: 'Това не е IFC файл.' } }];
    const [task] = await uploadAll([small('не е модел.ifc')], null);
    expect(sentTo()).toEqual([BIM, DOCS]);
    expect(task!.status).toBe('completed');
    expect(task!.message).toBe('Kept as a document: Това не е IFC файл.');
  });

  it('keeps a large refused model through the resumable documents upload', async () => {
    answers[DWG] = [{ status: 400, body: { detail: 'Неподдържана версия на чертежа.' } }];
    const [task] = await uploadAll([large('стар чертеж.dwg')], null);
    expect(sentTo()).toEqual([DWG]);
    expect(uploadResumable).toHaveBeenCalledTimes(1);
    expect(task!.status).toBe('completed');
    expect(task!.message).toBe('Kept as a document: Неподдържана версия на чертежа.');
  });

  it('does not turn "try again later" or a server failure into a document', async () => {
    answers[BIM] = [
      { status: 429, body: { detail: 'Too many uploads.' } },
      { status: 500, body: { detail: 'Internal error' } },
    ];
    const tasks = await uploadAll([small('първи.ifc'), small('втори.ifc')], null);
    expect(sentTo()).toEqual([BIM, BIM]);
    expect(tasks.map((t) => t.status)).toEqual(['error', 'error']);
  });

  it('a large document with no model extension still takes the resumable path', async () => {
    await uploadAll([large('Обяснителна записка.pdf')], null);
    expect(sentTo()).toEqual([]);
    expect(uploadResumable).toHaveBeenCalledTimes(1);
  });
});

describe('uploading into a chosen folder', () => {
  it('keeps a model in the folder someone chose', async () => {
    await uploadAll([small('Модел етаж 1.ifc')], 'document');
    expect(sentTo()).toEqual([DOCS]);
  });

  it('reports a refusal from the BIM folder instead of storing a document', async () => {
    answers[BIM] = [{ status: 400, body: { detail: 'Това не е IFC файл.' } }];
    const [task] = await uploadAll([small('не е модел.ifc')], 'bim_model');
    expect(sentTo()).toEqual([BIM]);
    expect(task!.status).toBe('error');
    expect(task!.error).toBe('Това не е IFC файл.');
  });
});
