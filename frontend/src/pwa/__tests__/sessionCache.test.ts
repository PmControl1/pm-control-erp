import { afterEach, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/useAuthStore';
import { isolateSessionQueries } from '../sessionCache';

afterEach(() => { vi.unstubAllGlobals(); useAuthStore.setState({ userId: null }); });

it('clears the prior account\'s React Query data on switch/logout, but keeps same-user refreshes', () => {
  const client = new QueryClient();
  const removeCache = vi.fn(async () => true);
  vi.stubGlobal('caches', { delete: removeCache });
  useAuthStore.setState({ userId: 'user-a' });
  const stop = isolateSessionQueries(client);
  try {
    client.setQueryData(['projects'], ['a-private']);
    useAuthStore.setState({ userId: 'user-a', accessToken: 'refreshed-a' });
    expect(client.getQueryData(['projects'])).toEqual(['a-private']);
    useAuthStore.setState({ userId: 'user-b' });
    expect(client.getQueryData(['projects'])).toBeUndefined();
    client.setQueryData(['projects'], ['b-private']);
    useAuthStore.setState({ userId: null });
    expect(client.getQueryData(['projects'])).toBeUndefined();
    expect(removeCache).toHaveBeenCalledWith('oce-api');
  } finally { stop(); client.clear(); }
});
