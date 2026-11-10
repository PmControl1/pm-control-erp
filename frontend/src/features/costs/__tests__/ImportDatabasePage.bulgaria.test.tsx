import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('@/shared/lib/api', async () => ({
  ...await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api'),
  apiGet: vi.fn().mockImplementation(async (url: string) => {
    if (url.includes('base-catalog')) return { families: [], loaded_regions: [], total_bases: 0, total_families: 0 };
    if (url.includes('/vector/status')) return { available: false, total_vectors: 0 };
    if (url.includes('catalogues-v3')) return { catalogues: [], server: { reachable: false } };
    return [];
  }),
}));

import { ImportDatabasePage } from '../ImportDatabasePage';

describe('Bulgarian cost imports', () => {
  it('keeps custom file imports and identifies Sofia without foreign-only importer panels', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={client}>
        <MemoryRouter><ImportDatabasePage /></MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByText('Sofia reference catalogue · by Data Driven Construction')).toBeInTheDocument();
    expect(screen.getByText('or upload your own file')).toBeInTheDocument();
    expect(container.querySelector('input[type="file"][accept*=".xlsx"]')).not.toBeNull();
    expect(screen.queryByText(/Vietnam|Indonesia|Toscana|prezzari regionali/i)).toBeNull();
    expect(screen.queryByTestId('regional-price-list-file')).toBeNull();
  });
});
