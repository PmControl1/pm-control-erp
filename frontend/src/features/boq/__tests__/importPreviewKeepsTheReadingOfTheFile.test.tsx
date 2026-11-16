// PM Project Management - the import preview keeps the reading the server made of the file.
// Licensed under the GNU AGPL v3.0 or later, like the rest of this program.
//
// A workbook in a layout the heading rules do not know is read with a recipe
// the workspace AI wrote: which rows and columns hold the bill. The preview
// says who read it and whether the lines add up to the file's own total, and
// sends the recipe back with every re-preview and with the import, so the bill
// imported is the bill previewed and the layout is not worked out twice.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';

import { ImportPreviewDialog } from '../ImportPreviewDialog';
import { checkNotes, columnLetter, readingOf, recipeField, totalCheckText, type ReadingCheck } from '../importReading';
import { useToastStore } from '@/stores/useToastStore';

const RECIPE = {
  version: 1,
  sheets: [
    {
      sheet: 'Бюджет',
      header_row: 5,
      first_row: 6,
      last_row: 48,
      columns: { description: 'B', unit: 'C', quantity: 'D', unit_rate: 'E', total: 'F' },
      file_total: { row: 51, column: 'F' },
    },
  ],
  currency: 'BGN',
  origin: 'ai',
};

const CHECK: ReadingCheck = {
  lines: 38,
  priced: 27,
  value_only: 11,
  values_sum: 1846320.5,
  imported_sum: 1845170.5,
  file_total: 1846320.5,
  file_total_cell: 'F51',
  total_matches: true,
  mismatch_count: 1,
  currency: 'BGN',
  ok: true,
};

const PREVIEW = {
  positions: [
    {
      ordinal: '1',
      code: '',
      description: 'Хидроизолация на основи',
      unit: 'сума',
      quantity: 1,
      unit_rate: '412386.50',
      total: '412386.50',
      is_section: false,
    },
  ],
  total_positions: 44,
  total_sections: 6,
  currency: 'BGN',
  source_format: 'xlsx',
  warnings: [],
  errors: [],
  skipped: 0,
  truncated: false,
  metadata: {
    original_columns: ['A', 'Етап на изграждането', 'мярка', 'количество', 'ед.цена', 'стойност, лв'],
    column_mapping: { '1': 'description', '2': 'unit', '3': 'quantity', '4': 'unit_rate', '5': 'total' },
    reading: { source: 'ai', recipe: RECIPE, check: CHECK },
  },
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function formOf(call: readonly unknown[] | undefined): FormData {
  return (call?.[1] as RequestInit).body as FormData;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  useToastStore.setState({ toasts: [] });
});

async function openPreview() {
  render(<ImportPreviewDialog open onClose={() => {}} boqId="boq-1" onImported={() => {}} />);
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File(['x'], 'Бюджет.xlsx')] } });
  const next = await screen.findByRole('button', { name: 'Continue' });
  await waitFor(() => expect(next).not.toBeDisabled());
  return next;
}

describe('the import preview keeps the reading of the file', () => {
  it('says the AI read the layout and that the lines add up to the total cell', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(json(PREVIEW));
    await openPreview();

    const reading = await screen.findByTestId('import-preview-reading');
    expect(reading).toHaveTextContent('The workspace AI worked out which rows and columns hold the bill');
    expect(screen.getByTestId('import-preview-total-check')).toHaveTextContent('the total in cell F51 of the file');
    expect(reading).toHaveTextContent('1 line(s) give a value that is not quantity × unit price');
    expect(reading).toHaveTextContent('11 line(s) give only a value');
  });

  it('sends the recipe back with the import, so the AI is not asked again', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(json(PREVIEW))
      .mockResolvedValueOnce(json({ imported: 38, created: 38, warnings: [] }));
    fireEvent.click(await openPreview());
    fireEvent.click(await screen.findByRole('button', { name: 'Import' }));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));

    expect(formOf(fetchSpy.mock.calls[0]).get('recipe')).toBeNull();
    expect(JSON.parse(String(formOf(fetchSpy.mock.calls[1]).get('recipe')))).toEqual(RECIPE);
  });

  it('re-previews a change of columns over the same recipe', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(json(PREVIEW))
      .mockResolvedValueOnce(json({ ...PREVIEW, metadata: { ...PREVIEW.metadata, reading: { source: 'person', recipe: RECIPE, check: CHECK } } }));
    await openPreview();

    fireEvent.click(screen.getByRole('button', { name: /Column mapping/ }));
    fireEvent.change(screen.getByLabelText('стойност, лв'), { target: { value: '' } });
    fireEvent.click(await screen.findByTestId('import-preview-apply-mapping'));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));

    const form = formOf(fetchSpy.mock.calls[1]);
    expect(JSON.parse(String(form.get('column_mapping')))).toEqual({ '5': '' });
    expect(JSON.parse(String(form.get('recipe')))).toEqual(RECIPE);
    expect(await screen.findByText('Read with the columns you chose')).toBeInTheDocument();
  });
});

describe('the words of a reading', () => {
  const t = (key: string, opts?: Record<string, unknown>) =>
    String(opts?.defaultValue ?? key).replace(/{{(\w+)}}/g, (_m, name: string) => String(opts?.[name] ?? ''));
  const fmt = (v: number) => v.toFixed(2);

  it('reads only a reading the server sent', () => {
    expect(readingOf(undefined)).toBeNull();
    expect(readingOf({ reading: 'x' })).toBeNull();
    expect(recipeField(readingOf({ reading: { source: 'rules' } }))).toBeNull();
    // The rules read the file the same way again; their recipe is not sent.
    expect(recipeField(readingOf({ reading: { source: 'rules', recipe: RECIPE } }))).toBeNull();
    expect(recipeField(readingOf({ reading: { source: 'saved', recipe: RECIPE } }))).toBe(JSON.stringify(RECIPE));
    expect(recipeField(readingOf(PREVIEW.metadata))).toBe(JSON.stringify(RECIPE));
  });

  it('says a total that differs, and nothing when the file has none', () => {
    expect(totalCheckText({ ...CHECK, total_matches: false, values_sum: 100 }, t, fmt)).toEqual({
      ok: false,
      text: "The lines add up to 100.00, but the file's total is 1846320.50. Check the rows and columns read",
    });
    expect(totalCheckText({ ...CHECK, file_total: null }, t, fmt)).toBeNull();
    expect(checkNotes({ ...CHECK, mismatch_count: 0, value_only: 0 }, t, fmt)).toEqual([]);
  });

  it('names columns as the spreadsheet does', () => {
    expect([0, 1, 25, 26, 27, 701, 702].map(columnLetter)).toEqual(['A', 'B', 'Z', 'AA', 'AB', 'ZZ', 'AAA']);
  });
});
