import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation } from 'react-router-dom';
import type { PackManifest, PartnerPacksResponse } from './packCatalog';

const api = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: api.apiGet };
});

const authState = vi.hoisted(() => ({ userRole: 'admin' as string | null }));
vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: (selector: (s: { userRole: string | null }) => unknown) => selector({ userRole: authState.userRole }),
}));

import { PacksCatalog } from './PacksCatalog';

function pack(slug: string, over: Partial<PackManifest>): PackManifest {
  return {
    slug,
    type: 'country',
    partner_name: slug,
    partner_url: null,
    pack_version: '1.0.0',
    description: '',
    default_locale: 'en',
    additional_locales: [],
    cwicr_regions: [],
    default_currency: 'EUR',
    default_tax_template: null,
    validation_rule_packs: [],
    default_modules: [],
    hidden_modules: [],
    branding: { primary_color: '#123456', accent_color: null, has_logo: false, has_favicon: false, powered_by_text: '' },
    has_onboarding_script: false,
    metadata: {},
    ...over,
  };
}

const DATA: PartnerPacksResponse = {
  active_slug: 'bulgaria-bg',
  installed: [
    pack('bulgaria-bg', { partner_name: 'Bulgaria pack', default_locale: 'bg', metadata: { country: 'BG' } }),
    pack('zz-germany', { partner_name: 'Germany pack', default_locale: 'de-DE', metadata: { country: 'DE' } }),
    pack('zz-france', { partner_name: 'France pack', default_locale: 'fr-FR', metadata: { country: 'FR' } }),
    pack('zz-brazil', { partner_name: 'Brazil pack', default_locale: 'pt-BR', default_currency: 'BRL', metadata: { country: 'BR' } }),
    pack('zz-infra', { type: 'industry', partner_name: 'Infrastructure pack' }),
  ],
};

let lastSearch = '';
function LocationProbe() {
  lastSearch = useLocation().search;
  return null;
}

function renderCatalog(url = '/packs', props: { embedded?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <PacksCatalog {...props} />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const cardNames = () => screen.queryAllByRole('heading', { level: 3 }).map((h) => h.textContent);

beforeEach(() => {
  authState.userRole = 'admin';
  lastSearch = '';
  api.apiGet.mockReset();
  api.apiGet.mockImplementation((path: string) => {
    if (path === '/v1/partner-pack/installed') return Promise.resolve(DATA);
    if (path.startsWith('/v1/partner-pack/applied')) return Promise.resolve({ applied: true, slug: 'bulgaria-bg', source: 'db' });
    return Promise.resolve({});
  });
});
afterEach(() => cleanup());

describe('PacksCatalog', () => {
  it('only shows the Bulgarian configuration, even when the server returns other packs', async () => {
    renderCatalog();
    await screen.findByText('Bulgaria pack');
    expect(screen.queryByText('France pack')).toBeNull();
    expect(screen.queryByText('Germany pack')).toBeNull();
    expect(screen.queryByText('Infrastructure pack')).toBeNull();
    expect(screen.queryByText('Brazil pack')).toBeNull();
  });

  it('keeps the automatic market read-only for administrators', async () => {
    renderCatalog('/modules?tab=packs', { embedded: true });
    const spot = await screen.findByTestId('packs-active-spotlight');
    expect(within(spot).getByText('Bulgaria pack')).toBeTruthy();
    expect(screen.queryByTestId('packs-install-toggle')).toBeNull();
    expect(screen.queryByRole('button', { name: /^deactivate/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /^activate/i })).toBeNull();
  });

  it('shows an empty state with a way out when nothing matches', async () => {
    renderCatalog('/packs?q=atlantis');
    const empty = await screen.findByTestId('packs-empty');
    fireEvent.click(within(empty).getByRole('button'));
    await screen.findByText('Bulgaria pack');
    expect(lastSearch).toBe('');
  });

  it('pins the active pack on the Modules tab and links to the packs page', async () => {
    renderCatalog('/modules?tab=packs', { embedded: true });
    const spot = await screen.findByTestId('packs-active-spotlight');
    expect(within(spot).getByText('Bulgaria pack')).toBeTruthy();
    expect(screen.getByTestId('packs-open-page').getAttribute('href')).toBe('/packs');
    expect(lastSearch).toBe('?tab=packs');
  });

  it('keeps the page read-only for a viewer', async () => {
    authState.userRole = 'viewer';
    renderCatalog();
    await screen.findByText('Bulgaria pack');
    expect(screen.queryByTestId('packs-install-toggle')).toBeNull();
    expect(screen.queryByRole('button', { name: /^activate/i })).toBeNull();
  });

  it('offers a retry when the list fails to load', async () => {
    api.apiGet.mockImplementation((path: string) =>
      path === '/v1/partner-pack/installed' ? Promise.reject(new Error('down')) : Promise.resolve({}),
    );
    renderCatalog();
    const alert = await screen.findByRole('alert');
    expect(within(alert).getByRole('button')).toBeTruthy();
    expect(cardNames()).toEqual([]);
  });
});
