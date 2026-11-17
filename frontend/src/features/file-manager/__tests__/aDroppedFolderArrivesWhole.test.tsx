// A dropped folder arrives whole. Every upload of a drop used to start at the
// same moment; the server takes 30 uploads a minute from one person, so in a
// folder of 40 the last 10 were refused with "too many uploads" and never
// sent again. Now a few go at a time, and a refusal of that kind is waited
// out, for as long as the server asks, and sent again.
import { type ReactNode } from 'react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { useFileUpload, retryAfterMs, PARALLEL_UPLOADS, THROTTLE_RETRIES } from '../useFileUpload';
import { useUploadQueueStore } from '@/stores/useUploadQueueStore';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      String(opts?.defaultValue ?? key).replace(/\{\{(\w+)\}\}/g, (_, k: string) => String(opts?.[k] ?? '')),
  }),
}));
vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: { getState: () => ({ accessToken: 'test-token' }) },
}));

const PROJECT = 'p-1';

/** A stand-in for the server's upload limit: ``limit`` uploads per ``windowMs``
 *  from one person, then 429 with ``Retry-After`` until the window moves on. */
function limitedServer(limit: number, windowMs: number, retryAfter: string) {
  const accepted: number[] = [];
  const stats = { stored: 0, refused: 0, inFlight: 0, mostInFlight: 0 };
  const handler = vi.fn(async () => {
    stats.inFlight += 1;
    stats.mostInFlight = Math.max(stats.mostInFlight, stats.inFlight);
    await new Promise((r) => setTimeout(r, 2));
    stats.inFlight -= 1;
    const now = Date.now();
    while (accepted.length && accepted[0]! <= now - windowMs) accepted.shift();
    if (accepted.length >= limit) {
      stats.refused += 1;
      return new Response(JSON.stringify({ detail: 'Too many uploads. Please wait a moment and try again.' }), {
        status: 429,
        headers: { 'Retry-After': retryAfter },
      });
    }
    accepted.push(now);
    stats.stored += 1;
    return new Response('{}', { status: 201 });
  });
  return { handler, stats };
}

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const folder = (n: number) =>
  Array.from({ length: n }, (_, i) => new File([`страница ${i + 1}`], `Протокол ${String(i + 1).padStart(2, '0')}.pdf`));

const settled = () =>
  useUploadQueueStore.getState().tasks.every((t) => t.status === 'completed' || t.status === 'error');

beforeEach(() => {
  useUploadQueueStore.setState({ tasks: [] });
});
afterEach(() => vi.unstubAllGlobals());

describe('a folder of 40 dropped at once', () => {
  it('all arrive, a few at a time, waiting out the limit instead of losing files', async () => {
    // 30 a "minute", where a minute is 300 ms, and the server asks for 1 s.
    const server = limitedServer(30, 300, '1');
    vi.stubGlobal('fetch', server.handler);
    const { result } = renderHook(() => useFileUpload(PROJECT), { wrapper });

    await act(() => result.current.doUpload(folder(40), null));
    await waitFor(() => expect(settled()).toBe(true), { timeout: 10_000 });

    const tasks = useUploadQueueStore.getState().tasks;
    expect(tasks.filter((t) => t.status === 'completed')).toHaveLength(40);
    expect(server.stats.stored).toBe(40);
    expect(server.stats.mostInFlight).toBeLessThanOrEqual(PARALLEL_UPLOADS);
    // Only the uploads already on their way when the limit was reached find
    // out the hard way; the rest wait without asking.
    expect(server.stats.refused).toBeLessThanOrEqual(PARALLEL_UPLOADS);
  });
});

describe('the queue while a batch is going', () => {
  it('shows the files not yet started as waiting', async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        await gate;
        return new Response('{}', { status: 201 });
      }),
    );
    const { result } = renderHook(() => useFileUpload(PROJECT), { wrapper });

    await act(() => result.current.doUpload(folder(5), null));
    // The queue lists the newest row first; read the rows in file order.
    const inFileOrder = () =>
      [...useUploadQueueStore.getState().tasks].sort((a, b) => a.filename.localeCompare(b.filename));
    await waitFor(() =>
      expect(inFileOrder().map((t) => t.status)).toEqual(['processing', 'processing', 'processing', 'queued', 'queued']),
    );
    expect(inFileOrder()[4]!.message).toBe('Waiting to upload…');

    release();
    await waitFor(() => expect(settled()).toBe(true));
    expect(useUploadQueueStore.getState().tasks.every((t) => t.status === 'completed')).toBe(true);
  });

  it('gives up on a file the server keeps refusing, and says why', async () => {
    const server = limitedServer(0, 60_000, '0');
    vi.stubGlobal('fetch', server.handler);
    const { result } = renderHook(() => useFileUpload(PROJECT), { wrapper });

    await act(() => result.current.doUpload(folder(1), null));
    await waitFor(() => expect(settled()).toBe(true));

    const [task] = useUploadQueueStore.getState().tasks;
    expect(task!.status).toBe('error');
    expect(task!.error).toBe('Too many uploads. Please wait a moment and try again.');
    expect(server.handler).toHaveBeenCalledTimes(THROTTLE_RETRIES + 1);
  });
});

describe('retryAfterMs', () => {
  const now = Date.parse('2026-11-17T10:00:00Z');
  it.each([
    ['60', 60_000],
    ['0', 0],
    [' 5 ', 5_000],
    ['86400', 300_000],
    ['Tue, 17 Nov 2026 10:00:30 GMT', 30_000],
    ['Tue, 17 Nov 2026 09:00:00 GMT', 0],
    ['soon', 60_000],
    [null, 60_000],
  ])('%s -> %i ms', (header, ms) => {
    expect(retryAfterMs(header, now)).toBe(ms);
  });
});
