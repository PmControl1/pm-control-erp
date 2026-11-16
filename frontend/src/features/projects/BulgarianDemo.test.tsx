import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { createInstance } from 'i18next';
import { apiPost } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { BulgarianDemoCard, BulgarianDemoLauncher, BulgarianDemoGuide, BULGARIAN_DEMO_ID, BULGARIAN_DEMOS } from './BulgarianDemo';
import { bulgarianDemoTranslations } from './bulgarianDemoTranslations';
import type { Project } from './api';

vi.mock('@/shared/lib/api', () => ({ apiPost: vi.fn() }));

const demo: Project = {
  id: 'bg-project', name: 'ДЕМО — Пловдив', status: 'active',
  metadata: { demo_id: BULGARIAN_DEMO_ID, BULGARIAN_DEMOS }, description: 'Sample project',
  region: 'BG', country_code: 'BG', classification_standard: '', currency: 'EUR',
  locale: 'bg', validation_rule_sets: ['boq_quality', 'bulgaria'], owner_id: 'admin',
  created_at: '2026-11-12T00:00:00Z', updated_at: '2026-11-12T00:00:00Z',
};

function Location() {
  return <output data-testid="location">{useLocation().pathname}</output>;
}

function mountCard() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter>
    <BulgarianDemoCard /><Location />
  </MemoryRouter></QueryClientProvider>);
  return client;
}

describe('Bulgarian project demo', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useProjectContextStore.setState({ activeProjectId: null, activeProjectName: '' });
    useToastStore.setState({ toasts: [] });
  });

  it('offers the demo immediately without a role or project-list prerequisite', () => {
    mountCard();
    expect(screen.getByTestId('bulgarian-demo-open')).toBeEnabled();
    expect(apiPost).not.toHaveBeenCalled();
  });

  it.each([false, true])('opens the current user demo and refreshes lists (already installed: %s)', async (alreadyInstalled) => {
    vi.mocked(apiPost).mockResolvedValue({ project_id: demo.id, project_name: demo.name, already_installed: alreadyInstalled });
    const client = mountCard();
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    fireEvent.click(screen.getByTestId('bulgarian-demo-open'));
    fireEvent.click(screen.getByTestId('bulgarian-demo-residential'));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/projects/bg-project'));
    expect(apiPost).toHaveBeenCalledExactlyOnceWith('/v1/projects/demo/bulgaria', { template_id: 'residential' });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['projects'] });
    expect(useProjectContextStore.getState().activeProjectId).toBe(demo.id);
  });

  it('makes the mobile action available and closes its menu after opening', async () => {
    vi.mocked(apiPost).mockResolvedValue({ project_id: demo.id, project_name: demo.name, already_installed: true });
    const onOpened = vi.fn();
    useProjectContextStore.setState({ activeProjectId: 'old-project', activeBOQId: 'old-boq' });
    const client = new QueryClient();
    render(<QueryClientProvider client={client}><MemoryRouter>
      <BulgarianDemoLauncher compact onOpened={onOpened} /><Location />
    </MemoryRouter></QueryClientProvider>);
    const button = screen.getByRole('button', { name: 'bg_demo.explore' });
    expect(button).toHaveTextContent('bg_demo.short');
    fireEvent.click(button);
    fireEvent.click(screen.getByTestId('bulgarian-demo-office-renovation'));
    await waitFor(() => expect(onOpened).toHaveBeenCalledOnce());
    expect(useProjectContextStore.getState().activeProjectId).toBe(demo.id);
    expect(useProjectContextStore.getState().activeBOQId).toBeNull();
  });

  it('shows errors without navigating away from the project list', async () => {
    vi.mocked(apiPost).mockRejectedValue(new Error('Permission denied'));
    mountCard();
    fireEvent.click(screen.getByTestId('bulgarian-demo-open'));
    fireEvent.click(screen.getByTestId('bulgarian-demo-residential'));
    await waitFor(() => expect(useToastStore.getState().toasts.some((toast) => toast.message === 'Permission denied')).toBe(true));
    expect(screen.getByTestId('location')).toHaveTextContent('/');
    expect(useProjectContextStore.getState().activeProjectId).toBeNull();
  });

  it.each(BULGARIAN_DEMOS)('shows the walkthrough and selects the $templateId demo before opening a module', (template) => {
    render(<MemoryRouter><BulgarianDemoGuide project={{ ...demo, metadata: { demo_id: template.demoId } }} /><Location /></MemoryRouter>);
    expect(screen.getAllByRole('link')).toHaveLength(9);
    fireEvent.click(screen.getByRole('link', { name: /3\. bg_demo\.tender/ }));
    expect(screen.getByTestId('location')).toHaveTextContent('/tendering');
    expect(useProjectContextStore.getState().activeProjectId).toBe(demo.id);
  });

  it.each(BULGARIAN_DEMOS)('opens only the selected $templateId template', async (template) => {
    vi.mocked(apiPost).mockResolvedValue({ project_id: template.templateId, project_name: 'Selected example', already_installed: false });
    mountCard();
    fireEvent.click(screen.getByTestId('bulgarian-demo-open'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(apiPost).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId(`bulgarian-demo-${template.templateId}`));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(`/projects/${template.templateId}`));
    expect(apiPost).toHaveBeenCalledExactlyOnceWith('/v1/projects/demo/bulgaria', { template_id: template.templateId });
  });

  it('closes the chooser without creating any projects', () => {
    mountCard();
    fireEvent.click(screen.getByTestId('bulgarian-demo-open'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(apiPost).not.toHaveBeenCalled();
  });

  it('blocks another selection while a template is being opened', async () => {
    let finish!: (result: unknown) => void;
    vi.mocked(apiPost).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    mountCard();
    fireEvent.click(screen.getByTestId('bulgarian-demo-open'));
    fireEvent.click(screen.getByTestId('bulgarian-demo-office-renovation'));
    await waitFor(() => expect(screen.getByTestId('bulgarian-demo-logistics-warehouse')).toBeDisabled());
    fireEvent.click(screen.getByTestId('bulgarian-demo-logistics-warehouse'));
    expect(apiPost).toHaveBeenCalledOnce();
    finish({ project_id: 'office', project_name: 'Office', already_installed: false });
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/projects/office'));
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
    expect(i18n.t('bg_demo.explore')).toBe('Разгледай демо проект');
    await i18n.changeLanguage('en');
    expect(i18n.t('bg_demo.explore')).toBe('Explore demo project');
  });
});
