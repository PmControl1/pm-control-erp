import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { BaseCatalogBrowser } from '../BaseCatalogBrowser';
import type { BaseCatalog, BaseVariant } from '../baseCatalog';

const SOFIA: BaseVariant = {
  region: 'BG_SOFIA', variant_id: 'BG_SOFIA', base_region: 'BG_SOFIA', market_catalog: '',
  active: false, market: 'Bulgaria', city: 'Sofia', language: 'Български', lang_code: 'bg',
  currency: 'BGN', flag: 'bg', positions: 55719, bundled: false, coefficient: false,
  loaded: false, loaded_positions: 0,
};
const CATALOG: BaseCatalog = {
  repo: 'reference', total_bases: 1, total_families: 1, loaded_regions: [],
  families: [{
    key: 'global', name: 'Global catalogue', norm_system: 'GESN / FER / TER', origin: 'Russia',
    origin_flag: 'ru', description: 'Reference methodology', market_count: 1,
    repriceable_markets: 0, positions: 55719, loaded_count: 0, variants: [SOFIA],
    attribution: 'Source publisher', licence: 'Source terms',
  }],
};

describe('Bulgarian reference catalogue', () => {
  it('shows Sofia directly without country search or a family selection step', () => {
    const load = vi.fn();
    render(<BaseCatalogBrowser catalog={CATALOG} onLoad={load} />);
    expect(screen.queryByRole('searchbox')).toBeNull();
    expect(screen.getAllByTestId('base-variant-card')).toHaveLength(1);
    expect(screen.getByText('Bulgaria')).toBeInTheDocument();
    expect(screen.getByText('BGN')).toBeInTheDocument();
    expect(screen.getByTestId('base-family-attribution')).toHaveTextContent('Source publisher');
    fireEvent.click(screen.getByRole('button', { name: /download/i }));
    expect(load).toHaveBeenCalledWith(SOFIA);
  });
});
