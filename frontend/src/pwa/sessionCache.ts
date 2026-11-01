import type { QueryClient } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/useAuthStore';

/** Drop in-memory results when sign-out or another account changes identity. */
export function isolateSessionQueries(client: Pick<QueryClient, 'cancelQueries' | 'clear'>): () => void {
  return useAuthStore.subscribe((current, previous) => {
    if (current.userId === previous.userId) return;
    void client.cancelQueries();
    client.clear();
    // Retire responses written by older service workers as well. The current
    // worker leaves API requests to the account-scoped IndexedDB cache.
    if (typeof caches !== 'undefined') void caches.delete('oce-api').catch(() => {});
  });
}
