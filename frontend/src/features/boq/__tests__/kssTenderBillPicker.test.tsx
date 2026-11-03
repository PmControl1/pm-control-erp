// PM Project Management - tests for the КСС tender-bill picker.
// Licensed under the GNU AGPL v3.0 or later, like the rest of this program.
//
// A Bulgarian КСС names the количествена сметка it was priced against, and the
// bulgaria rule set then compares the two line by line. The picker offers the
// project's other bills, writes the one metadata key and nothing else, clears
// it with None, keeps a link to a bill that is gone visible instead of showing
// None, and is read-only on a locked bill. It appears only where the bulgaria
// rules run.
//
// Run:  npx vitest run src/features/boq/__tests__/kssTenderBillPicker.test.tsx

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const api = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn() }));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return {
    ...actual,
    apiGet: (url: string) => api.get(url),
    apiPatch: (url: string, body: unknown) => api.patch(url, body),
  };
});

import { KssTenderBillPicker, runsBulgarianRules, tenderBillId } from '../KssTenderBillPicker';

const BILLS = [
  { id: 'kss', project_id: 'p1', name: 'КСС Витоша Строй' },
  { id: 'tender', project_id: 'p1', name: 'КС Жилищна сграда' },
  { id: 'other', project_id: 'p1', name: 'Бюджет' },
];

function renderPicker(props: { metadata?: Record<string, unknown> | null; locked?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <KssTenderBillPicker boqId="kss" projectId="p1" metadata={props.metadata} locked={props.locked ?? false} />
    </QueryClientProvider>,
  );
}

async function optionLabels(): Promise<string[]> {
  const select = screen.getByTestId('kss-tender-bill') as HTMLSelectElement;
  await waitFor(() => expect(select.options.length).toBeGreaterThan(1));
  return Array.from(select.options).map((o) => o.textContent ?? '');
}

beforeEach(() => {
  api.get.mockImplementation(async (url: string) => {
    expect(url).toBe('/v1/boq/boqs/?project_id=p1&offset=0&limit=100');
    return BILLS;
  });
  api.patch.mockResolvedValue({});
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('where the picker appears', () => {
  it('appears on a project that runs the bulgaria rule set or is in Bulgaria', () => {
    expect(runsBulgarianRules({ validation_rule_sets: ['boq_quality', 'bulgaria'] })).toBe(true);
    expect(runsBulgarianRules({ validation_rule_sets: [], country_code: 'bg' })).toBe(true);
    expect(runsBulgarianRules({ validation_rule_sets: [], region: 'BG_SOFIA' })).toBe(true);
    expect(runsBulgarianRules({ validation_rule_sets: [], region: 'Bulgaria' })).toBe(true);
  });

  it('stays away from everyone else', () => {
    expect(runsBulgarianRules(null)).toBe(false);
    expect(runsBulgarianRules({ validation_rule_sets: ['boq_quality', 'din276'], country_code: 'DE', region: 'DACH' })).toBe(false);
  });

  it('reads the link from the metadata and nothing else', () => {
    expect(tenderBillId({ kss_tender_bill_id: 'tender' })).toBe('tender');
    expect(tenderBillId({ kss_tender_bill_id: null })).toBe('');
    expect(tenderBillId(null)).toBe('');
  });
});

describe('the picker', () => {
  it('offers the other bills of the project, not the bill itself', async () => {
    renderPicker();
    expect(await optionLabels()).toEqual(['None', 'КС Жилищна сграда', 'Бюджет']);
  });

  it('offers a tender from later pages without sharing the first-page register cache', async () => {
    const firstPage = Array.from({ length: 100 }, (_, index) => ({
      id: `bill-${index}`,
      project_id: 'p1',
      name: `Bill ${index}`,
    }));
    api.get.mockImplementation(async (url: string) => {
      if (url.endsWith('offset=0&limit=100')) return firstPage;
      if (url.endsWith('offset=100&limit=100')) return [BILLS[1]];
      throw new Error(`Unexpected page: ${url}`);
    });
    renderPicker();
    await waitFor(() => expect(screen.getByRole('option', { name: 'КС Жилищна сграда' })).toBeTruthy());
    expect(api.get).toHaveBeenCalledWith('/v1/boq/boqs/?project_id=p1&offset=100&limit=100');
    fireEvent.change(screen.getByTestId('kss-tender-bill'), { target: { value: 'tender' } });
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/v1/boq/boqs/kss', { metadata: { kss_tender_bill_id: 'tender' } }));
  });

  it('writes the chosen bill into the one metadata key', async () => {
    renderPicker();
    await optionLabels();
    fireEvent.change(screen.getByTestId('kss-tender-bill'), { target: { value: 'tender' } });
    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
    expect(api.patch).toHaveBeenCalledWith('/v1/boq/boqs/kss', { metadata: { kss_tender_bill_id: 'tender' } });
  });

  it('clears the link with None', async () => {
    renderPicker({ metadata: { kss_tender_bill_id: 'tender', other: 1 } });
    await optionLabels();
    expect((screen.getByTestId('kss-tender-bill') as HTMLSelectElement).value).toBe('tender');
    fireEvent.change(screen.getByTestId('kss-tender-bill'), { target: { value: '' } });
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/v1/boq/boqs/kss', { metadata: { kss_tender_bill_id: null } }));
  });

  it('keeps a link to a bill that is gone visible', async () => {
    renderPicker({ metadata: { kss_tender_bill_id: 'deleted-bill' } });
    expect(await optionLabels()).toContain('No longer in this project');
    expect((screen.getByTestId('kss-tender-bill') as HTMLSelectElement).value).toBe('deleted-bill');
  });

  it('is read-only on a locked bill', async () => {
    renderPicker({ locked: true });
    await optionLabels();
    expect((screen.getByTestId('kss-tender-bill') as HTMLSelectElement).disabled).toBe(true);
  });
});
