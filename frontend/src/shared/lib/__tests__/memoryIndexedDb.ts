/** Small IndexedDB test adapter: the real store code still owns keys and account checks. */
export function memoryIndexedDb() {
  const tables = new Map<string, Map<string | number, unknown>>();
  let sequence = 0;
  const database = {
    objectStoreNames: { contains: (name: string) => tables.has(name) },
    createObjectStore: (name: string) => tables.set(name, new Map()),
    transaction(name: string) {
      const rows = tables.get(name)!;
      const tx = {
        oncomplete: null as (() => void) | null,
        objectStore: () => ({
          put(value: { path: string }) {
            rows.set(value.path, structuredClone(value));
            queueMicrotask(() => tx.oncomplete?.());
          },
          add(value: { id?: number }) {
            const entry = structuredClone({ ...value, id: ++sequence });
            rows.set(entry.id, entry);
            queueMicrotask(() => tx.oncomplete?.());
          },
          get(key: string) {
            const req = { result: rows.get(key), onsuccess: null as (() => void) | null };
            queueMicrotask(() => req.onsuccess?.());
            return req;
          },
          getAll() {
            const req = { result: [...rows.values()], onsuccess: null as (() => void) | null };
            queueMicrotask(() => {
              req.onsuccess?.();
              queueMicrotask(() => tx.oncomplete?.());
            });
            return req;
          },
          delete(key: string | number) {
            rows.delete(key);
            queueMicrotask(() => tx.oncomplete?.());
          },
          clear() {
            rows.clear();
            queueMicrotask(() => tx.oncomplete?.());
          },
        }),
      };
      return tx;
    },
  };
  return {
    open() {
      const req = { result: database, onupgradeneeded: null as (() => void) | null, onsuccess: null as (() => void) | null };
      queueMicrotask(() => {
        req.onupgradeneeded?.();
        req.onsuccess?.();
      });
      return req;
    },
    tables,
  };
}
