// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Old market links and saved filters must recover to the neutral catalogue
// after country-specific cases have been removed from the product.

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import React from "react";
import { useCasesStore } from "./useCasesStore";
import { CasesPage } from "./CasesPage";
import { PLAYBOOKS } from "./playbooks";

/* ── Real routing ────────────────────────────────────────────────────────
   The shared setup (src/test/setup.ts) stubs useSearchParams to a permanently
   empty set and useParams to `{}`. This file is about the address, so it puts
   the real hooks back: the page reads and writes the address the MemoryRouter
   below holds, and the probe beside it reads the same one. The factory
   registered last wins, so this replaces the stub for this file only. */

vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual };
});

/* ── Stable `t` (see casesProjectContext.test.tsx for why the shared mock's
   per-call `t` makes CasesList re-render without end) ───────────────────── */

vi.mock("react-i18next", () => {
  const stableT = (key: string, opts?: Record<string, unknown>) => {
    if (typeof opts === "object" && opts !== null && "defaultValue" in opts) {
      let template = opts.defaultValue as string;
      if (
        "count" in opts &&
        opts.count !== 1 &&
        typeof opts.defaultValue_other === "string"
      ) {
        template = opts.defaultValue_other;
      }
      return template.replace(/\{\{(\w+)\}\}/g, (_m, name: string) =>
        name in opts ? String(opts[name]) : `{{${name}}}`,
      );
    }
    return key;
  };
  const translation = {
    t: stableT,
    i18n: { language: "en", changeLanguage: vi.fn() },
  };
  return {
    useTranslation: () => translation,
    Trans: ({ children }: { children: React.ReactNode }) => children,
    initReactI18next: { type: "3rdParty", init: () => {} },
    I18nextProvider: ({ children }: { children: React.ReactNode }) => children,
  };
});

vi.mock("@/app/i18n", () => ({
  CORE_LANGUAGES: [{ code: "en", name: "English", flag: "gb", country: "gb" }],
  EXTRA_LANGUAGES: [],
  SUPPORTED_LANGUAGES: [
    { code: "en", name: "English", flag: "gb", country: "gb" },
  ],
  getLanguageByCode: () => ({
    code: "en",
    name: "English",
    flag: "gb",
    country: "gb",
  }),
  default: {
    use: () => ({ use: () => ({ use: () => ({ init: vi.fn() }) }) }),
    t: (key: string) => key,
    language: "en",
    changeLanguage: vi.fn(),
  },
}));

vi.mock("@tanstack/react-query", () => {
  const settled = (data: unknown) => ({
    data,
    isLoading: false,
    isError: false,
    isSuccess: true,
    error: null,
    refetch: vi.fn(),
  });
  return {
    useQuery: (opts: { queryKey?: unknown[] }) => {
      const root = String(opts?.queryKey?.[0] ?? "");
      if (root === "projects") return settled([]);
      return { ...settled(undefined), isSuccess: false };
    },
    useMutation: () => ({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isPending: false,
    }),
    useQueryClient: () => ({
      invalidateQueries: vi.fn(),
      setQueryData: vi.fn(),
    }),
    QueryClient: vi.fn(),
    QueryClientProvider: ({ children }: { children: React.ReactNode }) =>
      children,
  };
});

vi.mock("@/shared/lib/api", () => ({
  API_BASE: "/api",
  getAuthToken: () => "mock-token",
  extractErrorMessageFromBody: () => null,
  getErrorMessage: (err: unknown) => String(err),
  apiGet: vi.fn().mockResolvedValue([]),
  apiPost: vi.fn().mockResolvedValue({}),
  apiPatch: vi.fn().mockResolvedValue({}),
  apiPut: vi.fn().mockResolvedValue({}),
  apiDelete: vi.fn().mockResolvedValue(undefined),
  triggerDownload: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

// Every test here mounts the whole hub, two hundred and more cards, and the
// chip test re-renders it twice over. On a saturated CPU one mount alone
// can outlast the 15s default, so the file gets the room a lighter file
// does not need.
vi.setConfig({ testTimeout: 60_000 });

/* ── Helpers ──────────────────────────────────────────────────────────── */

/** Prints the address the router holds, so a test can read what a reader
 *  would copy out of the bar. Sits beside the page, under the same router. */
function AddressProbe() {
  const location = useLocation();
  return <output data-testid="address">{location.pathname + location.search}</output>;
}

/** Mount the hub at `address`; returns a reader for the current address. */
function renderHubAt(address: string): () => string {
  render(
    <MemoryRouter initialEntries={[address]}>
      <CasesPage />
      <AddressProbe />
    </MemoryRouter>,
  );
  return () => screen.getByTestId("address").textContent ?? "";
}

const region = () => useCasesStore.getState().region;

beforeEach(() => {
  localStorage.clear();
  // The store reads its persisted market once, when the module is evaluated,
  // so the reset has to go through the store rather than through storage.
  useCasesStore.getState().setRegion("all");
});

/* ── Tests ────────────────────────────────────────────────────────────── */

describe("obsolete market filters recover to the neutral catalogue", () => {
  it.each(["DE", "de", "GB", "ZZ", "all"])("removes ?market=%s without hiding cases", (market) => {
    const address = renderHubAt(`/cases?market=${market}`);
    expect(region()).toBe("all");
    expect(address()).toBe("/cases");
    expect(document.querySelectorAll('[role="button"]')).toHaveLength(PLAYBOOKS.length);
    expect(screen.queryByTestId("market-tile")).toBeNull();
  });

  it("clears a previously saved market and its persisted value", () => {
    useCasesStore.getState().setRegion("DE");
    expect(localStorage.getItem("oe_cases_region")).toBe("DE");
    const address = renderHubAt("/cases");
    expect(region()).toBe("all");
    expect(localStorage.getItem("oe_cases_region")).toBeNull();
    expect(address()).toBe("/cases");
    expect(document.querySelectorAll('[role="button"]')).toHaveLength(PLAYBOOKS.length);
  });

  it("clears both a saved market and a different market in an old link", () => {
    useCasesStore.getState().setRegion("GB");
    const address = renderHubAt("/cases?market=DE");
    expect(region()).toBe("all");
    expect(localStorage.getItem("oe_cases_region")).toBeNull();
    expect(address()).toBe("/cases");
  });

  it("preserves unrelated URL parameters while dropping the old country", () => {
    const address = renderHubAt("/cases?market=DE&source=bookmark");
    expect(address()).toBe("/cases?source=bookmark");
    expect(region()).toBe("all");
  });
});
