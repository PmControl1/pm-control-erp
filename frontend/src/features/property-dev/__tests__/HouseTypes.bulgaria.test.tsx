import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { HouseTypeEditModal } from '../HouseTypeEditModal';
import { HouseTypeSettingsPage } from '../HouseTypeSettingsPage';
import { createHouseTypeCatalogue, fetchHouseTypes, updateHouseTypeCatalogue, type HouseTypeCatalogueEntry } from '../api';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    createHouseTypeCatalogue: vi.fn().mockResolvedValue({}),
    updateHouseTypeCatalogue: vi.fn().mockResolvedValue({}),
    fetchHouseTypes: vi.fn().mockResolvedValue([]),
  };
});
vi.mock('@/shared/lib/projectList', () => ({
  fetchProjectList: vi.fn().mockResolvedValue([{ id: 'project', name: 'Bulgarian project' }]),
}));

afterEach(() => { cleanup(); vi.clearAllMocks(); });

function renderContent(content: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<MemoryRouter><QueryClientProvider client={client}>{content}</QueryClientProvider></MemoryRouter>);
}

describe('Bulgarian house types', () => {
  it('creates with Bulgaria and EUR without requiring country selection', async () => {
    renderContent(<HouseTypeEditModal entry={null} projects={[{ id: 'project', name: 'Bulgarian project' }]} onClose={vi.fn()} />);
    expect(screen.getByDisplayValue('България / Bulgaria')).toHaveAttribute('readonly');
    expect(screen.getByDisplayValue('EUR')).toHaveAttribute('readonly');
    expect(screen.queryByRole('option', { name: /Deutschland/ })).toBeNull();
    const project = screen.getAllByRole('combobox')[0];
    if (!project) throw new Error('Project selector is missing');
    fireEvent.change(project, { target: { value: 'project' } });
    fireEvent.change(screen.getByPlaceholderText('TYPE-A'), { target: { value: 'TYPE-BG' } });
    fireEvent.change(screen.getByPlaceholderText('2-bed coastal townhouse'), { target: { value: 'Bulgarian house' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(createHouseTypeCatalogue).toHaveBeenCalledWith(expect.objectContaining({
      project_id: 'project', code: 'TYPE-BG', name: 'Bulgarian house', country_code: 'BG', currency: 'EUR',
    })));
  });

  it.each([
    { country_code: 'GB', region_label: null, currency: 'GBP' },
    { country_code: null, region_label: 'Legacy custom region', currency: 'USD' },
  ])('preserves historical country, region and currency when renaming %s', async (market) => {
    const entry = { id: 'legacy', code: 'OLD', name: 'Existing house', ...market } as HouseTypeCatalogueEntry;
    renderContent(<HouseTypeEditModal entry={entry} projects={[]} onClose={vi.fn()} />);
    expect(screen.getByDisplayValue(market.currency)).toHaveValue(market.currency);
    fireEvent.change(screen.getByDisplayValue('Existing house'), { target: { value: 'Renamed house' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(updateHouseTypeCatalogue).toHaveBeenCalledWith('legacy', { name: 'Renamed house' }));
  });

  it('starts with the Bulgarian catalogue and keeps existing foreign entries accessible', async () => {
    renderContent(<HouseTypeSettingsPage />);
    await waitFor(() => expect(fetchHouseTypes).toHaveBeenCalledWith('BG', undefined));
    const country = screen.getAllByRole('combobox')[0];
    if (!country) throw new Error('Country filter is missing');
    expect(country).toHaveValue('BG');
    fireEvent.change(country, { target: { value: '' } });
    await waitFor(() => expect(fetchHouseTypes).toHaveBeenCalledWith(undefined, undefined));
  });
});
