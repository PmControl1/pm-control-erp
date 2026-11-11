import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { createInstance } from 'i18next';
import { apiPost } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { BulgarianDemoCard, BulgarianDemoGuide, BULGARIAN_DEMO_ID } from './BulgarianDemo';
import { bulgarianDemoTranslations } from './bulgarianDemoTranslations';
import type { Project } from './api';

vi.mock('@/shared/lib/api', () => ({ apiPost: vi.fn() }));

const demo: Project = {
  id: 'bg-project', name: 'ДЕМО — Пловдив', status: 'active',
  metadata: { demo_id: BULGARIAN_DEMO_ID }, description: 'Sample project',
  region: 'BG', country_code: 'BG', classification_standard: '', currency: 'EUR',
  locale: 'bg', validation_rule_sets: ['boq_quality', 'bulgaria'], owner_id: 'admin',
  created_at: '2026-11-12T00:00:00Z', updated_at: '2026-11-12T00:00:00Z',
};

function Location() {
  return <output data-testid="location">{useLocation().pathname}</output>;
}

function mountCard(role?: string, projects: Project[] = []) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter>
    <BulgarianDemoCard role={role} projects={projects} /><Location />
  </MemoryRouter></QueryClientProvider>);
  return client;
}

describe('Bulgarian project demo', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useProjectContextStore.setState({ activeProjectId: null, activeProjectName: '' });
    useToastStore.setState({ toasts: [] });
  });

  it('only offers creation to an administrator', () => {
    mountCard('viewer');
    expect(screen.queryByTestId('bulgarian-demo-open')).toBeNull();
    expect(apiPost).not.toHaveBeenCalled();
  });

  it('creates the demo explicitly, refreshes lists and opens the returned project', async () => {
    vi.mocked(apiPost).mockResolvedValue({ project_id: demo.id, project_name: demo.name, already_installed: false });
    const client = mountCard('admin');
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    fireEvent.click(screen.getByTestId('bulgarian-demo-open'));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/projects/bg-project'));
    expect(apiPost).toHaveBeenCalledExactlyOnceWith('/v1/projects/demo/bulgaria', {});
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['projects'] });
    expect(useProjectContextStore.getState().activeProjectId).toBe(demo.id);
  });

  it('lets an existing member open a shared demo without reinstalling it', () => {
    mountCard('viewer', [demo]);
    fireEvent.click(screen.getByTestId('bulgarian-demo-open'));
    expect(screen.getByTestId('location')).toHaveTextContent('/projects/bg-project');
    expect(apiPost).not.toHaveBeenCalled();
  });

  it('shows errors without navigating away from the project list', async () => {
    vi.mocked(apiPost).mockRejectedValue(new Error('Permission denied'));
    mountCard('admin');
    fireEvent.click(screen.getByTestId('bulgarian-demo-open'));
    await waitFor(() => expect(useToastStore.getState().toasts.some((toast) => toast.message === 'Permission denied')).toBe(true));
    expect(screen.getByTestId('location')).toHaveTextContent('/');
    expect(useProjectContextStore.getState().activeProjectId).toBeNull();
  });

  it('selects the demo before opening a global module from its walkthrough', () => {
    render(<MemoryRouter><BulgarianDemoGuide project={demo} /><Location /></MemoryRouter>);
    expect(screen.getAllByRole('link')).toHaveLength(9);
    fireEvent.click(screen.getByRole('link', { name: /3\. bg_demo\.tender/ }));
    expect(screen.getByTestId('location')).toHaveTextContent('/tendering');
    expect(useProjectContextStore.getState().activeProjectId).toBe(demo.id);
  });

  it('keeps the walkthrough off real projects', () => {
    render(<MemoryRouter><BulgarianDemoGuide project={{ ...demo, metadata: {} }} /></MemoryRouter>);
    expect(screen.queryByRole('region')).toBeNull();
  });

  it('provides complete Bulgarian and English walkthrough text', async () => {
    const i18n = createInstance();
    await i18n.init({ lng: 'bg', fallbackLng: 'en', keySeparator: false, resources: {
      bg: { translation: bulgarianDemoTranslations.bg },
      en: { translation: bulgarianDemoTranslations.en },
    } });
    expect(Object.keys(bulgarianDemoTranslations.bg)).toEqual(Object.keys(bulgarianDemoTranslations.en));
    expect(i18n.t('bg_demo.create')).toBe('Създай демо проект');
    await i18n.changeLanguage('en');
    expect(i18n.t('bg_demo.create')).toBe('Create demo project');
  });
});
