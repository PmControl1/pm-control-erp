import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('@/shared/lib/api', async () => ({
  ...await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api'),
  apiGet: vi.fn().mockResolvedValue({ ai_ready: true, workspace_managed: true }),
  apiPost: vi.fn().mockResolvedValue({ answer: 'Reference result', sources: [], query: 'Concrete' }),
}));

import { apiPost } from '@/shared/lib/api';
import { AdvisorPage } from '../AdvisorPage';

describe('Bulgarian advisor sources', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Element.prototype.scrollIntoView = vi.fn();
  });

  it.each(['/advisor', '/advisor?region=DE_BERLIN&q=Concrete', '/advisor?region=BG_SOFIA&q=Concrete'])(
    'uses Sofia automatically when opened at %s', async (url) => {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      render(
        <QueryClientProvider client={client}>
          <MemoryRouter initialEntries={[url]}><AdvisorPage /></MemoryRouter>
        </QueryClientProvider>,
      );
      expect(screen.getByText('Bulgaria · Sofia catalogue')).toBeInTheDocument();
      expect(screen.queryByRole('combobox')).toBeNull();
      const input = screen.getByRole('textbox');
      fireEvent.change(input, { target: { value: 'Concrete' } });
      fireEvent.click(screen.getByRole('button', { name: 'Send' }));
      await waitFor(() => expect(apiPost).toHaveBeenCalledWith(
        '/v1/ai/advisor/chat/',
        expect.objectContaining({ message: 'Concrete', region: 'BG_SOFIA' }),
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      ));
    },
  );
});
