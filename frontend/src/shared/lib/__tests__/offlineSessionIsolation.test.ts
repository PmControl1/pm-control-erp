import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useAuthStore } from '@/stores/useAuthStore';
import { memoryIndexedDb } from './memoryIndexedDb';

vi.mock('../errorLogger', () => ({ logError: vi.fn(), logApiError: vi.fn() }));
vi.mock('../intlLocale', () => ({ getDigitSystem: () => 'latn' }));

import { apiGet, apiPost, downloadWithAuth, fetchWithAuth } from '../api';
import { cacheResponse, clearCache, clearMutationQueue, getCachedResponse, getQueuedMutations, queueMutation } from '../offlineStore';
import { replayMutations } from '@/shared/hooks/useOnlineStatus';

const storage = memoryIndexedDb();
const originalRefreshSession = useAuthStore.getState().refreshSession;
const account = (id: string | null) => useAuthStore.setState({ userId: id, accessToken: id ? `token-${id}` : null });

beforeEach(async () => {
  vi.stubGlobal('indexedDB', storage);
  account('user-a');
  await clearCache();
  await clearMutationQueue();
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); account(null); useAuthStore.setState({ refreshSession: originalRefreshSession }); });

describe('offline state on a shared browser', () => {
  it('keeps cached responses separate and never adopts old unowned entries', async () => {
    storage.tables.get('apiCache')!.set('/v1/projects/', { path: '/v1/projects/', data: ['legacy-private'], expiresAt: Date.now() + 60_000 });
    expect(await getCachedResponse('/v1/projects/')).toBeNull();
    await cacheResponse('/v1/projects/', ['a-private']);
    account('user-b');
    expect(await getCachedResponse('/v1/projects/')).toBeNull();
    await cacheResponse('/v1/projects/', ['b-private']);
    account(null);
    expect(await getCachedResponse('/v1/projects/')).toBeNull();
    account('user-a');
    expect(await getCachedResponse('/v1/projects/')).toEqual(['a-private']);
  });

  it.each(['json', 'raw'] as const)('does not return or cache a response whose request outlived its account (%s)', async (transport) => {
    let finish!: (response: Response) => void;
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { finish = resolve; })));
    const request = transport === 'json' ? apiGet('/v1/projects/') : fetchWithAuth('/api/v1/projects/');
    account('user-b');
    finish(new Response(JSON.stringify(['a-private']), { status: 200 }));
    await expect(request).rejects.toMatchObject({ name: 'AbortError' });
    expect(await getCachedResponse('/v1/projects/')).toBeNull();
  });

  it('does not save a pending file download after another account signs in', async () => {
    let finish!: (blob: Blob) => void;
    const response = new Response('private document', { status: 200 });
    vi.spyOn(response, 'blob').mockImplementation(() => new Promise<Blob>((resolve) => { finish = resolve; }));
    vi.stubGlobal('fetch', vi.fn(async () => response));
    const download = downloadWithAuth('/api/v1/files/private', 'private.txt');
    await vi.waitFor(() => expect(finish).toBeTypeOf('function'));
    account('user-b');
    finish(new Blob(['private document']));
    await expect(download).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('does not queue an old account\'s in-flight failure for a new account', async () => {
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);
    let fail!: (error: Error) => void;
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((_resolve, reject) => { fail = reject; })));
    const request = apiPost('/v1/projects/', { name: 'A private project' });
    account('user-b');
    fail(new TypeError('Failed to fetch'));
    await expect(request).rejects.toMatchObject({ name: 'AbortError' });
    expect(await getQueuedMutations()).toEqual([]);
  });

  it.each(['json', 'raw'] as const)('does not retry an old request with a new account after refresh (%s)', async (transport) => {
    const send = vi.fn(async () => new Response('{}', { status: 401 }));
    vi.stubGlobal('fetch', send);
    useAuthStore.setState({ refreshSession: async () => { account('user-b'); return { token: 'token-user-b' }; } });
    const pending = transport === 'json' ? apiGet('/v1/projects/') : fetchWithAuth('/api/v1/projects/');
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(send).toHaveBeenCalledTimes(1);
    expect(useAuthStore.getState().userId).toBe('user-b');
  });

  it('rejects a raw refresh retry that finishes after the account changes', async () => {
    let finish!: (response: Response) => void;
    const send = vi.fn()
      .mockResolvedValueOnce(new Response('{}', { status: 401 }))
      .mockImplementationOnce(() => new Promise<Response>((resolve) => { finish = resolve; }));
    vi.stubGlobal('fetch', send);
    useAuthStore.setState({ refreshSession: async () => ({ token: 'refreshed-a' }) });
    const pending = fetchWithAuth('/api/v1/projects/');
    await vi.waitFor(() => expect(finish).toBeTypeOf('function'));
    account('user-b');
    finish(new Response(JSON.stringify(['a-private']), { status: 200 }));
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(useAuthStore.getState().userId).toBe('user-b');
  });

  it('serves each account\'s own cached JSON while offline', async () => {
    await cacheResponse('/v1/projects/', ['a-private']);
    account('user-b');
    await cacheResponse('/v1/projects/', ['b-private']);
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch'); }));
    await expect(apiGet('/v1/projects/')).resolves.toEqual(['b-private']);
  });

  it('retains queued writes for their owner and never replays legacy or other-account writes', async () => {
    const mutation = { method: 'POST' as const, path: '/v1/projects/', body: { name: 'A only' }, queuedAt: Date.now(), retries: 0 };
    await queueMutation(mutation);
    storage.tables.get('mutationQueue')!.set(99, { ...mutation, id: 99 });
    account('user-b');
    const send = vi.fn(async (_input: string, _init?: RequestInit) => new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', send);
    expect(await getQueuedMutations()).toEqual([]);
    await replayMutations();
    expect(send).not.toHaveBeenCalled();
    account('user-a');
    expect(await getQueuedMutations()).toHaveLength(1);
    await replayMutations();
    expect(send).toHaveBeenCalledTimes(1);
    expect(send.mock.calls[0]?.[1]).toMatchObject({ headers: { Authorization: 'Bearer token-user-a' } });
    expect(await getQueuedMutations()).toEqual([]);
  });

  it('stops a drain when the account changes between writes', async () => {
    const mutation = { method: 'POST' as const, path: '/v1/projects/', queuedAt: Date.now(), retries: 0 };
    await queueMutation(mutation);
    await queueMutation(mutation);
    const send = vi.fn(async () => { account('user-b'); return new Response('{}', { status: 200 }); });
    vi.stubGlobal('fetch', send);
    await replayMutations();
    expect(send).toHaveBeenCalledTimes(1);
    account('user-a');
    expect(await getQueuedMutations()).toHaveLength(1);
  });

  it('clears only the signed-in account\'s queued work, preserving other owners and blocked legacy entries', async () => {
    const mutation = { method: 'POST' as const, path: '/v1/projects/', queuedAt: Date.now(), retries: 0 };
    await queueMutation({ ...mutation, body: { name: 'A unsynced' } });
    storage.tables.get('mutationQueue')!.set(99, { ...mutation, id: 99 });
    account('user-b');
    await queueMutation({ ...mutation, body: { name: 'B discarded' } });
    await clearMutationQueue();
    expect(await getQueuedMutations()).toEqual([]);
    account('user-a');
    expect(await getQueuedMutations()).toMatchObject([{ body: { name: 'A unsynced' } }]);
    expect(storage.tables.get('mutationQueue')!.get(99)).toMatchObject({ id: 99 });
  });
});
