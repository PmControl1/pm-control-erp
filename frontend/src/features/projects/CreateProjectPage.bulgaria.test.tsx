import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return { ...actual, projectsApi: {
    ...actual.projectsApi,
    list: vi.fn().mockResolvedValue([]),
    wizardPresets: vi.fn().mockResolvedValue([]),
    create: vi.fn().mockResolvedValue({ id: 'project-bg', name: 'Bulgarian site' }),
    applyProfile: vi.fn().mockResolvedValue({}),
  } };
});
vi.mock('./ProjectClassificationFields', () => ({ ProjectClassificationFields: () => null }));
vi.mock('./ProjectWorksField', () => ({ ProjectWorksField: () => null }));
vi.mock('@/features/geo-hub/AddressAutocomplete', () => ({
  AddressAutocomplete: ({ onSelect }: { onSelect: (value: unknown) => void }) => (
    <button type="button" onClick={() => onSelect({ country_code: 'de', display_name: 'Berlin',
      address_parts: { country: 'Germany', city: 'Berlin' }, lat: 52.52, lon: 13.4 })}>
      Choose foreign site
    </button>
  ),
}));

import { CreateProjectModal, projectCoreForm } from './CreateProjectPage';
import { projectsApi, type Project } from './api';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import { useToastStore } from '@/stores/useToastStore';

function openProjectForm() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><CreateProjectModal open onClose={vi.fn()} /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Bulgarian project creation', () => {
  beforeEach(() => { vi.clearAllMocks(); useToastStore.setState({ toasts: [] }); });

  it('creates a Bulgarian EUR project from its name despite a foreign saved currency', async () => {
    usePreferencesStore.setState({ currency: 'GBP' });
    openProjectForm();
    fireEvent.click(screen.getByRole('button', { name: /Quick create/ }));
    fireEvent.change(screen.getByLabelText(/projects.project_name/), { target: { value: 'Bulgarian site' } });
    fireEvent.click(screen.getByRole('button', { name: 'common.create' }));
    await waitFor(() => expect(projectsApi.create).toHaveBeenCalledOnce());
    expect(vi.mocked(projectsApi.create).mock.calls[0]?.[0]).toMatchObject({
      name: 'Bulgarian site', country_code: 'BG', region: 'BG', currency: 'EUR', locale: 'bg',
    });
  });

  it('does not offer foreign markets or classification systems in new project setup', () => {
    openProjectForm();
    fireEvent.click(screen.getByRole('button', { name: /Quick create/ }));
    const region = screen.getByLabelText('Region');
    expect(region).toBeDisabled();
    expect(region).toHaveValue('BG');
    expect(screen.queryByRole('option', { name: /DACH|NRM|MasterFormat|DIN 276/ })).toBeNull();
    expect(screen.getByLabelText('Currency')).toBeDisabled();
  });

  it('rejects a foreign geocoder selection before changing the site country', () => {
    openProjectForm();
    fireEvent.click(screen.getByRole('button', { name: /Quick create/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Show all options' }));
    fireEvent.click(screen.getByRole('button', { name: 'Choose foreign site' }));
    expect(useToastStore.getState().toasts.some((toast) =>
      toast.type === 'error' && toast.title === 'Choose a site address in Bulgaria.',
    )).toBe(true);
    expect(screen.getByLabelText('Country')).toHaveValue('Bulgaria');
    expect(screen.getByLabelText('City')).toHaveValue('');
  });

  it('preserves existing project settings when setup is reopened', () => {
    const existing = { name: 'Legacy project', description: 'Original', region: 'DACH',
      classification_standard: 'din276', currency: 'CHF', locale: 'de' } as Project;
    expect(projectCoreForm(existing, 'EUR')).toEqual(existing);
    expect(existing.region).toBe('DACH');
  });
});
