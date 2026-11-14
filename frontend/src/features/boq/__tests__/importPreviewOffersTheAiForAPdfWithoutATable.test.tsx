// PM Project Management - a PDF the table reader cannot read is offered to the workspace AI.
// Licensed under the GNU AGPL v3.0 or later, like the rest of this program.
//
// The bill toolbar's Import window previews with the native readers only, and
// a PDF has none for text without ruled cells: it was refused, and nothing in
// the window led to the AI reading the server already had. The refusal now
// comes with "Read with AI", which posts the file to the auto route; that
// route hands such a PDF to the workspace AI and imports its rows.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';

import { ImportPreviewDialog } from '../ImportPreviewDialog';

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

const NO_TABLE = {
  detail: {
    code: 'pdf_no_table',
    params: { pages: 3 },
    message: 'The PDF has no table with ruled cells to read.',
  },
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function choose(name: string) {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File(['%PDF-1.7'], name)] } });
}

describe('a PDF without a ruled table', () => {
  it('is offered to the AI, which imports it through the auto route', async () => {
    const onImported = vi.fn();
    const onClose = vi.fn();
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(json(NO_TABLE, 400))
      .mockResolvedValueOnce(
        json({ imported: 12, warnings: [{ code: 'read_by_ai', message: 'read by AI' }], method: 'ai' }),
      );
    render(<ImportPreviewDialog open onClose={onClose} boqId="boq-1" onImported={onImported} />);
    choose('kss.pdf');

    const offer = await screen.findByTestId('import-preview-ai-offer');
    expect(offer).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Read with AI' }));

    await waitFor(() => expect(onImported).toHaveBeenCalledTimes(1));
    expect(onClose).toHaveBeenCalled();
    expect(String(fetchSpy.mock.calls[1]?.[0])).toBe('/api/v1/boq/boqs/boq-1/import/auto/');
    const sent = (fetchSpy.mock.calls[1]?.[1] as RequestInit).body as FormData;
    expect((sent.get('file') as File).name).toBe('kss.pdf');
  });

  it('shows what the AI refused and stays open', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(json(NO_TABLE, 400))
      .mockResolvedValueOnce(
        json({ detail: { code: 'import_pdf_no_text', params: { pages: 2 }, message: 'The PDF has no text.' } }, 400),
      );
    const onClose = vi.fn();
    render(<ImportPreviewDialog open onClose={onClose} boqId="boq-1" onImported={() => {}} />);
    choose('scan.pdf');

    fireEvent.click(await screen.findByRole('button', { name: 'Read with AI' }));
    expect(await screen.findByText(/The PDF has no text/)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('is not offered for a spreadsheet', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      json({ detail: { code: 'spreadsheet_empty_file', params: {}, message: 'empty' } }, 400),
    );
    render(<ImportPreviewDialog open onClose={() => {}} boqId="boq-1" onImported={() => {}} />);
    choose('kss.xlsx');
    await waitFor(() => expect(screen.queryByText(/Parsing file/)).toBeNull());
    expect(screen.queryByTestId('import-preview-ai-offer')).toBeNull();
  });
});
