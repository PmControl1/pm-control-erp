// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// A stale API catalogue must not reintroduce foreign setup choices.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const { followCostDbLoad, loadBaseMarket, embeddingModelStatus } = vi.hoisted(() => ({
  followCostDbLoad: vi.fn(),
  loadBaseMarket: vi.fn(),
  embeddingModelStatus: vi.fn(),
}));

function variant(over = {}) {
  return {
    region: 'TR_NATIONAL',
    variant_id: 'TR_NATIONAL',
    base_region: 'TR_NATIONAL',
    market_catalog: '',
    active: false,
    market: 'Turkiye',
    city: 'National',
    language: 'Turkce',
    lang_code: 'tr',
    text_lang_code: 'tr',
    currency: 'TRY',
    flag: 'tr',
    positions: 22494,
    bundled: true,
    coefficient: false,
    loaded: false,
    loaded_positions: 0,
    ...over,
  };
}

const HOME = variant();
const PARIS = variant({
  variant_id: 'TR_NATIONAL:FR_PARIS_fr',
  market_catalog: 'FR_PARIS_fr',
  market: 'France',
  city: 'Paris',
  language: 'Francais',
  lang_code: 'fr',
  text_lang_code: 'fr',
  currency: 'EUR',
  flag: 'fr',
});

const CATALOG = {
  repo: 'x',
  total_bases: 2,
  total_families: 1,
  loaded_regions: [],
  families: [
    {
      // Keyed "china" so the family starts expanded.
      key: 'china',
      name: 'Turkiye (Birim Fiyat)',
      norm_system: 'Birim Fiyat',
      origin: 'Turkiye',
      origin_flag: 'tr',
      description: '',
      market_count: 2,
      repriceable_markets: 49,
      positions: 22494,
      loaded_count: 0,
      variants: [HOME, PARIS],
    },
  ],
};

vi.mock('@/features/ai-estimator/api', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    aiEstimatorApi: { ...actual.aiEstimatorApi, embeddingModelStatus, installEmbeddingModel: vi.fn() },
  };
});

vi.mock('@/features/costs/baseCatalog', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, useBaseCatalog: () => ({ data: CATALOG }), loadBaseMarket };
});

vi.mock('../costDbLoad', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, followCostDbLoad };
});

import { StepDataSetup } from '../OnboardingWizard';

function renderStep() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <StepDataSetup onNext={vi.fn()} onBack={() => undefined} selectedLang="en" backgroundLoad={false} />
    </QueryClientProvider>,
  );
}

describe('StepDataSetup, Bulgarian catalogue setup', () => {
  beforeEach(() => {
    followCostDbLoad.mockReset();
    loadBaseMarket.mockReset();
    embeddingModelStatus.mockResolvedValue({ enabled: false, installed: false });
  });

  it('does not offer foreign bases from a stale server response', async () => {
    renderStep();
    await screen.findByRole('button', { name: 'Load Database' });
    expect(screen.queryByTestId('base-variant-card')).toBeNull();
    expect(screen.queryByText('Turkiye (Birim Fiyat)')).toBeNull();
    expect(screen.queryByText('France')).toBeNull();
    expect(followCostDbLoad).not.toHaveBeenCalled();
    expect(loadBaseMarket).not.toHaveBeenCalled();
  });
});
