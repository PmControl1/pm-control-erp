import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useAuthStore } from '@/stores/useAuthStore';
import { createFieldTimeSender, enqueueEntry, getFieldTimeQueue, pickFieldTimeStorage, resetFieldTimeQueueForTests } from './offlineQueue';
import { useFieldTimeOfflineSync } from './useFieldTimeOfflineSync';

vi.mock('@/shared/hooks/useOnlineStatus', () => ({ useOnlineStatus: () => false }));
vi.mock('@/shared/lib/api', async () => {
  const { useAuthStore: auth } = await import('@/stores/useAuthStore');
  return { API_BASE: '/api', getAuthToken: () => auth.getState().accessToken };
});

const account = (id: string | null) => useAuthStore.setState({ userId: id, accessToken: id ? `token-${id}` : null });
const day = (key: string) => ({ entry_key: key, project_id: 'project-a', date: '2026-11-01', lines: [], submit: true });

beforeEach(() => {
  resetFieldTimeQueueForTests();
  vi.stubGlobal('indexedDB', undefined);
  account('user-a');
});
afterEach(() => {
  resetFieldTimeQueueForTests();
  account(null);
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('field-time work belongs to the account that recorded it', () => {
  it('keeps A\'s days for A and never shows or replays them as B', async () => {
    await enqueueEntry(day('a-day'));
    const aQueue = getFieldTimeQueue();
    const send = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', send);
    account('user-b');
    const bQueue = getFieldTimeQueue();
    expect(await bQueue.pending()).toEqual([]);
    expect(await aQueue.pending()).toEqual([]);
    expect((await aQueue.drain()).results).toEqual([]);
    expect(send).not.toHaveBeenCalled();
    account('user-a');
    expect(getFieldTimeQueue()).toBe(aQueue);
    expect(await aQueue.pendingCount()).toBe(1);
    await aQueue.drain();
    expect(send).toHaveBeenCalledTimes(1);
    expect(send.mock.calls[0]?.[1]).toMatchObject({ headers: { Authorization: 'Bearer token-user-a' } });
    expect(await aQueue.pendingCount()).toBe(0);
  });

  it('refuses a held sender and discard after a change of account', async () => {
    await enqueueEntry(day('a-day'));
    const aQueue = getFieldTimeQueue();
    const [op] = await aQueue.pending();
    expect(op).toBeDefined();
    const sender = createFieldTimeSender();
    const send = vi.fn();
    vi.stubGlobal('fetch', send);
    account('user-b');
    await expect(sender(op!)).rejects.toMatchObject({ name: 'AbortError' });
    await expect(aQueue.discard(op!.clientOpId)).rejects.toMatchObject({ name: 'AbortError' });
    expect(send).not.toHaveBeenCalled();
    account('user-a');
    expect(await aQueue.pendingCount()).toBe(1);
  });

  it('stops an in-flight drain before another day can be sent under a later login', async () => {
    await enqueueEntry(day('first'));
    await enqueueEntry(day('second'));
    const queue = getFieldTimeQueue();
    const send = vi.fn(async () => {
      account('user-b');
      return new Response('{}', { status: 200 });
    });
    vi.stubGlobal('fetch', send);
    await expect(queue.drain()).rejects.toMatchObject({ name: 'AbortError' });
    expect(send).toHaveBeenCalledTimes(1);
    expect(await getFieldTimeQueue().pending()).toEqual([]);
    account('user-a');
    // The first response crossed the account boundary, so both idempotent
    // entries remain for their owner rather than being discarded as B.
    expect(await queue.pendingCount()).toBe(2);
  });

  it('opens a distinct database for each owner and never adopts the old unowned database', async () => {
    const open = vi.fn((_name: string, _version?: number) => { throw new Error('Stop after recording the database name'); });
    vi.stubGlobal('indexedDB', { open });
    await pickFieldTimeStorage().getAll();
    account('user-b');
    await pickFieldTimeStorage().getAll();
    expect(open.mock.calls.map(([name]) => name)).toEqual(['oe_field_time_offline:user-a', 'oe_field_time_offline:user-b']);
  });

  it('hides a mounted pending list immediately on switch and restores it only for its owner', async () => {
    await enqueueEntry(day('a-day'));
    const { result, unmount } = renderHook(() => useFieldTimeOfflineSync());
    try {
      await waitFor(() => expect(result.current.pending).toHaveLength(1));
      act(() => { account('user-b'); });
      expect(result.current.pending).toEqual([]);
      expect(result.current.lastSummary).toBeNull();
      await waitFor(() => expect(result.current.pending).toEqual([]));
      act(() => { account('user-a'); });
      await waitFor(() => expect(result.current.pending).toHaveLength(1));
    } finally { unmount(); }
  });
});
