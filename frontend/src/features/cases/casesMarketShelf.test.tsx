// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The product catalogue retains the neutral examples and their search/layout
// while omitting every country shelf and its regional-pack offers.

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within, fireEvent, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";

import { PLAYBOOKS } from "./playbooks";
import { useCasesStore } from "./useCasesStore";
import { CasesPage } from "./CasesPage";

/* ── The UI language under test, flipped per case (see casesHomeMarketOrder) ── */

const uiLanguage = vi.hoisted(() => ({ current: "en" }));

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
    i18n: {
      get language() {
        return uiLanguage.current;
      },
      changeLanguage: vi.fn(),
    },
  };
  return {
    useTranslation: () => translation,
    Trans: ({ children }: { children: React.ReactNode }) => children,
    initReactI18next: { type: "3rdParty", init: () => {} },
    I18nextProvider: ({ children }: { children: React.ReactNode }) => children,
  };
});

/* ── The pack list, controlled per test ─────────────────────────────────── */

const packMock = vi.hoisted(() => ({
  usePartnerPack: vi.fn(),
  useInstalledPacks: vi.fn(),
  partnerLogoUrl: vi.fn(() => "/api/v1/partner-pack/logo"),
}));
vi.mock("@/shared/hooks/usePartnerPack", () => packMock);

// The apply dialog is the modules feature's and drags its API along; nothing
// here opens it.
vi.mock("@/features/modules/PartnerPackApplyDialog", () => ({
  PartnerPackApplyDialog: () => null,
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

vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useParams: () => ({}),
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
  };
});

// Every test here mounts the whole hub, two hundred and more cards, and the
// pack-state test re-renders it twice over. On a saturated CPU one mount alone
// can outlast the 15s default, so the file gets the room a lighter file
// does not need.
vi.setConfig({ testTimeout: 60_000 });

/* ── Fixtures ───────────────────────────────────────────────────────────── */

function packOf(slug: string, country: string, name: string) {
  return {
    slug,
    partner_name: name,
    type: "country",
    description: `Pre-configured for ${country}: standards, tax and currency`,
    default_locale: "en-US",
    default_currency: "EUR",
    default_tax_template: "de_vat_19",
    pack_version: "0.2.0",
    validation_rule_packs: ["din276"],
    validation_rule_sets: [],
    metadata: { country },
    branding: { primary_color: "#123456", accent_color: null },
  };
}

/** Two of the packs the released wheel carries. Germany is deliberately not
 *  among them: no build a user installs has a German pack, and the tile has to
 *  say so. */
const INSTALLED = [packOf("uk-jct", "GB", "UK JCT"), packOf("india-cpwd", "IN", "India CPWD")];

function packsAnswered(activeSlug: string | null = null) {
  packMock.useInstalledPacks.mockReturnValue({
    isLoading: false,
    data: { active_slug: activeSlug, installed: INSTALLED },
  });
}

function packsInFlight() {
  packMock.useInstalledPacks.mockReturnValue({ isLoading: true, data: undefined });
}

function renderHub(language: string) {
  uiLanguage.current = language;
  return render(
    <MemoryRouter initialEntries={["/cases"]}>
      <CasesPage />
    </MemoryRouter>,
  );
}

/** The case cards, in document order. `role="button"` is written in exactly
 *  one place in CasesPage.tsx, the card root; the shelf tiles are real
 *  buttons and carry no role attribute. */
const cards = (container: HTMLElement) =>
  Array.from(container.querySelectorAll<HTMLElement>('[role="button"]'));

beforeEach(() => {
  cleanup();
  localStorage.clear();
  useCasesStore.getState().clearFilters();
  uiLanguage.current = "en";
  packMock.useInstalledPacks.mockReset();
  packsAnswered();
});

describe("country-neutral case catalogue", () => {
  it.each(["bg", "en", "de"])("has no market shelf for a %s reader", (language) => {
    const { container } = renderHub(language);
    expect(PLAYBOOKS.length).toBeGreaterThan(0);
    expect(PLAYBOOKS.every((pb) => !pb.region)).toBe(true);
    expect(cards(container)).toHaveLength(PLAYBOOKS.length);
    expect(screen.queryAllByTestId("market-tile")).toHaveLength(0);
    expect(screen.queryByRole("group", { name: "Market" })).toBeNull();
  });

  it("keeps the ordinary company and role filters", () => {
    renderHub("bg");
    const company = screen.getByRole("group", { name: "My company" });
    fireEvent.click(within(company).getAllByRole("button")[0]!);
    expect(screen.getByRole("group", { name: "Your role" })).toBeTruthy();
    expect(screen.queryAllByTestId("market-tile")).toHaveLength(0);
  });

  it("finds neutral cases by their title", () => {
    const { container } = renderHub("en");
    const target = PLAYBOOKS[0]!;
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: target.titleDefault } });
    const found = cards(container);
    expect(found.length).toBeGreaterThan(0);
    expect(found.some((card) => card.textContent?.includes(target.titleDefault))).toBe(true);
  });

  it("does not show a country shelf while regional packs load", () => {
    packsInFlight();
    renderHub("en");
    expect(screen.queryAllByTestId("market-tile")).toHaveLength(0);
  });
});

describe("layout contract", () => {
  it("lets the header wrap below sm, where its action column is full width", () => {
    renderHub("en");
    const row = screen.getByRole("heading", { level: 1 }).closest("div.relative");
    expect(row).not.toBeNull();
    expect(row!.classList.contains("flex-wrap")).toBe(true);
    expect(row!.classList.contains("sm:flex-nowrap")).toBe(true);
  });

  it("lets a long one-word label break inside its tile", () => {
    renderHub("en");
    const company = screen.getByRole("group", { name: "My company" });
    const label = within(company).getByText("General contractor");
    expect(label.classList.contains("break-words")).toBe(true);
    const role = screen.getByRole("group", { name: "Your role" });
    expect(within(role).getByText("Estimator").classList.contains("break-words")).toBe(true);
  });

  it("draws six card columns at xl and keeps eight for 2xl", () => {
    const { container } = renderHub("en");
    const grid = cards(container)[0]!.parentElement!;
    expect(grid.classList.contains("xl:grid-cols-6")).toBe(true);
    expect(grid.classList.contains("2xl:grid-cols-8")).toBe(true);
    expect(grid.classList.contains("xl:grid-cols-8")).toBe(false);
  });
});
