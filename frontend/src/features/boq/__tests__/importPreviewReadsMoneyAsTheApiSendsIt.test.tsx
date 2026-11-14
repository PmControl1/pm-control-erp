// PM Project Management - the import preview survives the rates the API sends.
// Licensed under the GNU AGPL v3.0 or later, like the rest of this program.
//
// The preview endpoint sends rates and totals as decimal strings ("12.5"),
// like every money field in the API, while quantities stay numbers. The
// dialog formatted them as numbers, so the first priced row threw
// "value.toFixed is not a function" and the bill editor went down with it:
// no spreadsheet with a price in it could be imported. The other preview tests
// mocked plain numbers, which is how this went unnoticed.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';

import { ImportPreviewDialog } from '../ImportPreviewDialog';

// The shape /api/v1/boq/import/preview/ answers for a КСС, as the server sends it.
const KSS_PREVIEW = {
  positions: [
    {
      ordinal: 'I',
      description: 'I. ЗЕМНИ РАБОТИ',
      unit: 'section',
      quantity: 0.0,
      unit_rate: '0.0',
      total: '0.0',
      is_section: true,
      classification: {},
      metadata: {},
    },
    {
      ordinal: '1',
      description: 'Изкоп с багер на транспорт',
      unit: 'м3',
      quantity: 1250.0,
      unit_rate: '12.5',
      total: '15625.0',
      is_section: false,
      classification: { code: '02.01.01' },
      metadata: {},
    },
    {
      ordinal: '2',
      description: 'Непредвидени разходи 10%',
      unit: 'сума',
      quantity: 1.0,
      unit_rate: '1562.5',
      total: '1562.5',
      is_section: false,
      classification: {},
      metadata: { contingency: true },
    },
  ],
  total_positions: 3,
  total_sections: 1,
  currency: 'BGN',
  source_format: 'xlsx',
  warnings: [],
  errors: [],
  skipped: 0,
  truncated: false,
  metadata: {},
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('import preview with money as decimal strings', () => {
  it('shows the priced rows and goes on to import them', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(json(KSS_PREVIEW))
      .mockResolvedValueOnce(json({ imported: 2, warnings: [] }));
    render(<ImportPreviewDialog open onClose={() => {}} boqId="boq-1" onImported={() => {}} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(['x'], 'kss.xlsx')] } });

    expect(await screen.findByText('Изкоп с багер на транспорт')).toBeInTheDocument();
    const row = screen.getByText('Изкоп с багер на транспорт').closest('tr') as HTMLTableRowElement;
    const cells = Array.from(row.querySelectorAll('td')).map((td) => td.textContent?.replace(/\s/g, ''));
    // Ordinal, description, unit, quantity, rate, total: the money read as numbers.
    expect(cells[4]).toMatch(/^12[.,]50$/);
    expect(cells[5]).toMatch(/^15[.,]?625[.,]00$/);

    const next = screen.getByRole('button', { name: 'Continue' });
    fireEvent.click(next);
    fireEvent.click(await screen.findByRole('button', { name: 'Import' }));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
    expect(String(fetchSpy.mock.calls[1]?.[0])).toBe('/api/v1/boq/boqs/boq-1/import/auto/?background=true');
  });
});
