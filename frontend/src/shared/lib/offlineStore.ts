// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Offline data persistence using IndexedDB.
 * Provides caching for API responses and a queue for offline mutations.
 *
 * Uses the raw IndexedDB API (no dependencies) for maximum lightweight.
 */

import { useAuthStore } from '@/stores/useAuthStore';

const DB_NAME = 'oe_offline';
const DB_VERSION = 1;

// Store names
const CACHE_STORE = 'apiCache';
const MUTATION_QUEUE = 'mutationQueue';

/* ── Types ─────────────────────────────────────────────────────────── */

export interface CachedResponse {
  /** API path used as key */
  path: string;
  /** Cached response data */
  data: unknown;
  /** Timestamp of when this was cached */
  cachedAt: number;
  /** Cache expiry in ms (default 1 hour) */
  expiresAt: number;
}

export interface QueuedMutation {
  /** Account that queued this write. Legacy unowned entries are never replayed. */
  ownerId?: string;
  /** Auto-incremented id */
  id?: number;
  /** HTTP method */
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  /** API path */
  path: string;
  /** Request body */
  body?: unknown;
  /** Timestamp when queued */
  queuedAt: number;
  /** Number of retry attempts */
  retries: number;
}

/* ── DB initialization ─────────────────────────────────────────────── */

let dbPromise: Promise<IDBDatabase> | null = null;

function getDB(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise;

  dbPromise = new Promise<IDBDatabase>((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);

    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(CACHE_STORE)) {
        db.createObjectStore(CACHE_STORE, { keyPath: 'path' });
      }
      if (!db.objectStoreNames.contains(MUTATION_QUEUE)) {
        db.createObjectStore(MUTATION_QUEUE, { keyPath: 'id', autoIncrement: true });
      }
    };

    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });

  return dbPromise;
}

/* ── Cache operations ──────────────────────────────────────────────── */

const DEFAULT_TTL = 60 * 60 * 1000; // 1 hour

/**
 * Cache an API response for offline use.
 */
export async function cacheResponse(
  path: string,
  data: unknown,
  ttl = DEFAULT_TTL,
  ownerId = useAuthStore.getState().userId,
): Promise<void> {
  if (!ownerId || ownerId !== useAuthStore.getState().userId) return;
  try {
    const db = await getDB();
    if (ownerId !== useAuthStore.getState().userId) return;
    const tx = db.transaction(CACHE_STORE, 'readwrite');
    const store = tx.objectStore(CACHE_STORE);
    const entry: CachedResponse = {
      path: JSON.stringify([ownerId, path]),
      data,
      cachedAt: Date.now(),
      expiresAt: Date.now() + ttl,
    };
    store.put(entry);
    await new Promise<void>((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch {
    // IndexedDB unavailable — silently fail
  }
}

/**
 * Retrieve a cached response. Returns null if not found or expired.
 */
export async function getCachedResponse<T>(
  path: string,
  ownerId = useAuthStore.getState().userId,
): Promise<T | null> {
  if (!ownerId || ownerId !== useAuthStore.getState().userId) return null;
  try {
    const db = await getDB();
    if (ownerId !== useAuthStore.getState().userId) return null;
    const tx = db.transaction(CACHE_STORE, 'readonly');
    const store = tx.objectStore(CACHE_STORE);
    const key = JSON.stringify([ownerId, path]);
    const req = store.get(key);

    return new Promise<T | null>((resolve) => {
      req.onsuccess = () => {
        if (ownerId !== useAuthStore.getState().userId) {
          resolve(null);
          return;
        }
        const entry = req.result as CachedResponse | undefined;
        if (!entry) {
          resolve(null);
          return;
        }
        if (Date.now() > entry.expiresAt) {
          // Expired — clean up
          const delTx = db.transaction(CACHE_STORE, 'readwrite');
          delTx.objectStore(CACHE_STORE).delete(key);
          resolve(null);
          return;
        }
        resolve(entry.data as T);
      };
      req.onerror = () => resolve(null);
    });
  } catch {
    return null;
  }
}

/**
 * Clear all cached responses.
 */
export async function clearCache(): Promise<void> {
  try {
    const db = await getDB();
    const tx = db.transaction(CACHE_STORE, 'readwrite');
    tx.objectStore(CACHE_STORE).clear();
    await new Promise<void>((resolve) => {
      tx.oncomplete = () => resolve();
    });
  } catch {
    // ignore
  }
}

/* ── Mutation queue operations ─────────────────────────────────────── */

/**
 * Queue a mutation for later execution when back online.
 */
export async function queueMutation(mutation: Omit<QueuedMutation, 'id'>): Promise<void> {
  const ownerId = mutation.ownerId ?? useAuthStore.getState().userId;
  if (!ownerId || ownerId !== useAuthStore.getState().userId) return;
  try {
    const db = await getDB();
    if (ownerId !== useAuthStore.getState().userId) return;
    const tx = db.transaction(MUTATION_QUEUE, 'readwrite');
    tx.objectStore(MUTATION_QUEUE).add({ ...mutation, ownerId });
    await new Promise<void>((resolve) => {
      tx.oncomplete = () => resolve();
    });
  } catch {
    // ignore
  }
}

/**
 * Get all queued mutations.
 */
export async function getQueuedMutations(): Promise<QueuedMutation[]> {
  const ownerId = useAuthStore.getState().userId;
  if (!ownerId) return [];
  try {
    const db = await getDB();
    const tx = db.transaction(MUTATION_QUEUE, 'readonly');
    const store = tx.objectStore(MUTATION_QUEUE);
    const req = store.getAll();

    return new Promise<QueuedMutation[]>((resolve) => {
      req.onsuccess = () => resolve(
        ownerId === useAuthStore.getState().userId
          ? ((req.result ?? []) as QueuedMutation[]).filter((mutation) => mutation.ownerId === ownerId)
          : [],
      );
      req.onerror = () => resolve([]);
    });
  } catch {
    return [];
  }
}

/**
 * Remove a mutation from the queue after successful replay.
 */
export async function removeMutation(id: number): Promise<void> {
  try {
    const db = await getDB();
    const tx = db.transaction(MUTATION_QUEUE, 'readwrite');
    tx.objectStore(MUTATION_QUEUE).delete(id);
    await new Promise<void>((resolve) => {
      tx.oncomplete = () => resolve();
    });
  } catch {
    // ignore
  }
}

/**
 * Clear this account's pending writes. Other accounts and legacy unowned
 * entries stay untouched; a shared browser must not discard their work.
 */
export async function clearMutationQueue(): Promise<void> {
  const ownerId = useAuthStore.getState().userId;
  if (!ownerId) return;
  try {
    const db = await getDB();
    if (ownerId !== useAuthStore.getState().userId) return;
    const tx = db.transaction(MUTATION_QUEUE, 'readwrite');
    const store = tx.objectStore(MUTATION_QUEUE);
    const request = store.getAll();
    request.onsuccess = () => {
      if (ownerId !== useAuthStore.getState().userId) return;
      for (const mutation of (request.result ?? []) as QueuedMutation[]) {
        if (mutation.ownerId === ownerId && mutation.id !== undefined) store.delete(mutation.id);
      }
    };
    await new Promise<void>((resolve) => {
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
      tx.onabort = () => resolve();
    });
  } catch {
    // ignore
  }
}
