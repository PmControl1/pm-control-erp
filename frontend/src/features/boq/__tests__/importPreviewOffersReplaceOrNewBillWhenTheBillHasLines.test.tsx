// PM Project Management - a file whose numbers the bill already has: replace, or a new bill.
// Licensed under the GNU AGPL v3.0 or later, like the rest of this program.
//
// Every row of a КСС imported into a bill that already had its numbers was
// refused on its own, so the window said only "could not be saved, no rows
// were imported" (or the bill came in with lines missing). The server now
// refuses the file before writing anything (``import_bill_has_lines``) and the
// window offers the two ways on: replace the bill's lines, or import the file
// into a new bill in the same project and open it.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';

import { ImportPreviewDialog } from '../ImportPreviewDialog';

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

const PREVIEW = {
  positions: [
    {
      ordinal: '1',
      description: 'Изкоп',
      unit: 'м3',
      quantity: 10,
      unit_rate: '5',
      total: '50',
      is_section: false,
      classification: {},
      metadata: {},
    },
  ],
  total_positions: 1,
  total_sections: 0,
  currency: 'BGN',
  source_format: 'xlsx',
  warnings: [],
  errors: [],
  skipped: 0,
  truncated: false,
  metadata: {},
};

const JOB = { job_id: 'job-1', status: 'pending', progress_percent: 0, phase: null, reused: false };
const REFUSED = {
  job_id: 'job-1',
  status: 'failed',
  progress_percent: 0,
  error: 'The bill already has 10 lines, and numbers in the file (I, 1, 2) are taken.',
  error_code: 'import_bill_has_lines',
  error_params: { lines: 10, taken: 'I, 1, 2' },
};
const DONE = { job_id: 'job-2', status: 'success', progress_percent: 100, result: { imported: 1, warnings: [] } };

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

async function refusedImport(fetchSpy: ReturnType<typeof vi.spyOn>, onOpenBill = vi.fn()) {
  render(
    <ImportPreviewDialog
      open
      onClose={() => {}}
      boqId="boq-1"
      projectId="project-1"
      onImported={() => {}}
      onOpenBill={onOpenBill}
    />,
  );
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File(['x'], 'КСС обект 2.xlsx')] } });
  fireEvent.click(await screen.findByRole('button', { name: 'Continue' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Import' }));
  expect(await screen.findByTestId('import-preview-bill-has-lines')).toBeInTheDocument();
  expect(fetchSpy).toHaveBeenCalledTimes(3);
}

describe('a bill that already has the file numbers', () => {
  it('replaces the bill lines when asked', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(json(PREVIEW))
      .mockResolvedValueOnce(json(JOB, 202))
      .mockResolvedValueOnce(json(REFUSED))
      .mockResolvedValueOnce(json({ ...JOB, job_id: 'job-2' }, 202))
      .mockResolvedValueOnce(json(DONE));
    await refusedImport(fetchSpy);

    fireEvent.click(screen.getByRole('button', { name: "Replace the bill's 10 lines" }));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(5));
    expect(String(fetchSpy.mock.calls[3]?.[0])).toBe('/api/v1/boq/boqs/boq-1/import/auto/?background=true&replace=true');
  });

  it('imports into a new bill named after the file, and opens it', async () => {
    const onOpenBill = vi.fn();
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(json(PREVIEW))
      .mockResolvedValueOnce(json(JOB, 202))
      .mockResolvedValueOnce(json(REFUSED))
      .mockResolvedValueOnce(json({ id: 'boq-new', project_id: 'project-1' }, 201))
      .mockResolvedValueOnce(json({ ...JOB, job_id: 'job-2' }, 202))
      .mockResolvedValueOnce(json(DONE));
    await refusedImport(fetchSpy, onOpenBill);

    fireEvent.click(screen.getByRole('button', { name: 'Import into a new bill' }));
    await waitFor(() => expect(onOpenBill).toHaveBeenCalledWith('boq-new'));
    const created = fetchSpy.mock.calls[3];
    expect(String(created?.[0])).toBe('/api/v1/boq/boqs/');
    expect(JSON.parse(String((created?.[1] as RequestInit).body))).toEqual({ project_id: 'project-1', name: 'КСС обект 2' });
    expect(String(fetchSpy.mock.calls[4]?.[0])).toBe('/api/v1/boq/boqs/boq-new/import/auto/?background=true');
  });
});
