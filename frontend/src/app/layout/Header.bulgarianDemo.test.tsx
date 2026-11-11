import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation } from 'react-router-dom';
import type { ReactNode } from 'react';
import { apiPost } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { ProjectSwitcher } from './Header';
import ProjectSelector from '@/features/erp-chat/full-page/topbar/ProjectSelector';

vi.mock('@/shared/lib/projectList', () => ({ fetchProjectList: vi.fn() }));
vi.mock('@/shared/lib/api', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/shared/lib/api')>(),
  apiPost: vi.fn(),
}));

function Location() {
  return <output data-testid="location">{useLocation().pathname}</output>;
}

function mount(element: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter>
    {element}<Location />
  </MemoryRouter></QueryClientProvider>);
  return client;
}

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ isAuthenticated: true, userRole: 'viewer', userId: 'sample-viewer' });
  useProjectContextStore.setState({ activeProjectId: null, activeProjectName: '', activeBOQId: null });
  vi.mocked(fetchProjectList).mockResolvedValue([]);
});

describe('demo discovery in project selectors', () => {
  it('lets a viewer with no projects choose an office demo from the global picker', async () => {
    vi.mocked(apiPost).mockImplementation(async () => {
      vi.mocked(fetchProjectList).mockResolvedValue([{ id: 'own-demo', name: 'ДЕМО' }]);
      return { project_id: 'own-demo', project_name: 'ДЕМО', already_installed: false };
    });
    mount(<ProjectSwitcher />);
    fireEvent.click(screen.getByRole('button', { name: 'Switch Project' }));
    await screen.findByText('No projects yet');
    fireEvent.click(within(screen.getByTestId('header-project-picker')).getByRole('button', { name: 'bg_demo.explore' }));
    const chooser = screen.getByRole('dialog', { name: 'bg_demo.choose_title' });
    for (const template of ['residential', 'office-renovation', 'logistics-warehouse']) {
      expect(within(chooser).getByTestId(`bulgarian-demo-${template}`)).toBeEnabled();
    }
    expect(apiPost).not.toHaveBeenCalled();
    const office = within(chooser).getByTestId('bulgarian-demo-office-renovation');
    // A real pointer press in this portal must not trigger the picker's
    // document-level outside-click listener and unmount the chooser.
    fireEvent.mouseDown(office);
    expect(screen.getByTestId('bulgarian-demo-chooser')).toBeInTheDocument();
    fireEvent.click(office);
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/projects/own-demo'));
    expect(apiPost).toHaveBeenCalledExactlyOnceWith('/v1/projects/demo/bulgaria', { template_id: 'office-renovation' });
    expect(useProjectContextStore.getState().activeProjectId).toBe('own-demo');
    expect(screen.queryByRole('button', { name: 'bg_demo.explore' })).toBeNull();
  });

  it('keeps the demo launcher visible while the global project list is loading', () => {
    vi.mocked(fetchProjectList).mockReturnValue(new Promise(() => {}));
    mount(<ProjectSwitcher />);
    fireEvent.click(screen.getByRole('button', { name: 'Switch Project' }));
    expect(screen.getByRole('button', { name: 'bg_demo.explore' })).toBeEnabled();
  });

  it('keeps the demo launcher outside global project search results', async () => {
    vi.mocked(fetchProjectList).mockResolvedValue([{ id: 'real-project', name: 'Actual building' }]);
    mount(<ProjectSwitcher />);
    fireEvent.click(screen.getByRole('button', { name: 'Switch Project' }));
    await screen.findByText('Actual building');
    fireEvent.change(screen.getByPlaceholderText('Search...'), { target: { value: 'unmatched search' } });
    expect(screen.queryByText('Actual building')).toBeNull();
    expect(screen.getByRole('button', { name: 'bg_demo.explore' })).toBeEnabled();
  });

  it('lets a viewer with no projects choose a warehouse demo from the chat project selector', async () => {
    vi.mocked(apiPost).mockResolvedValue({ project_id: 'chat-demo', project_name: 'ДЕМО', already_installed: true });
    mount(<ProjectSelector />);
    fireEvent.click(screen.getByRole('button', { name: /All Projects/ }));
    await screen.findByText('No projects');
    fireEvent.click(screen.getByRole('button', { name: 'bg_demo.explore' }));
    const warehouse = screen.getByTestId('bulgarian-demo-logistics-warehouse');
    fireEvent.mouseDown(warehouse);
    expect(screen.getByTestId('bulgarian-demo-chooser')).toBeInTheDocument();
    fireEvent.click(warehouse);
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/projects/chat-demo'));
    expect(apiPost).toHaveBeenCalledExactlyOnceWith('/v1/projects/demo/bulgaria', { template_id: 'logistics-warehouse' });
    expect(useProjectContextStore.getState().activeProjectId).toBe('chat-demo');
    expect(screen.queryByRole('button', { name: 'bg_demo.explore' })).toBeNull();
  });

  it('keeps the chat demo launcher visible while its project list is loading', () => {
    vi.mocked(fetchProjectList).mockReturnValue(new Promise(() => {}));
    mount(<ProjectSelector />);
    fireEvent.click(screen.getByRole('button', { name: /All Projects/ }));
    expect(screen.getByRole('button', { name: 'bg_demo.explore' })).toBeEnabled();
  });

  it.each(['global', 'chat'] as const)('cancels the %s chooser without creating a project and restores focus', async (picker) => {
    mount(picker === 'global' ? <ProjectSwitcher /> : <ProjectSelector />);
    fireEvent.click(screen.getByRole('button', { name: picker === 'global' ? 'Switch Project' : /All Projects/ }));
    await screen.findByText(picker === 'global' ? 'No projects yet' : 'No projects');
    const launcher = screen.getByRole('button', { name: 'bg_demo.explore' });
    launcher.focus();
    fireEvent.click(launcher);
    const close = within(screen.getByTestId('bulgarian-demo-chooser')).getByRole('button', { name: 'Close' });
    fireEvent.mouseDown(close);
    fireEvent.click(close);
    expect(screen.queryByTestId('bulgarian-demo-chooser')).toBeNull();
    expect(apiPost).not.toHaveBeenCalled();
    expect(screen.getByTestId('location')).toHaveTextContent('/');
    await waitFor(() => expect(launcher).toHaveFocus());
  });

  it.each(['global', 'chat'] as const)('keeps the %s chooser mounted during an installation', async (picker) => {
    vi.mocked(apiPost).mockReturnValue(new Promise(() => {}));
    mount(picker === 'global' ? <ProjectSwitcher /> : <ProjectSelector />);
    fireEvent.click(screen.getByRole('button', { name: picker === 'global' ? 'Switch Project' : /All Projects/ }));
    await screen.findByText(picker === 'global' ? 'No projects yet' : 'No projects');
    fireEvent.click(screen.getByRole('button', { name: 'bg_demo.explore' }));
    const residential = screen.getByTestId('bulgarian-demo-residential');
    residential.focus();
    fireEvent.click(residential);
    await waitFor(() => expect(screen.getByTestId('bulgarian-demo-residential')).toBeDisabled());
    fireEvent.keyDown(document.activeElement ?? residential, { key: 'Escape' });
    expect(screen.getByTestId('bulgarian-demo-chooser')).toBeInTheDocument();
    // Browsers may blur a focused control as soon as it becomes disabled.
    // The pending operation must stay protected when Escape targets the page.
    residential.blur();
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(screen.getByTestId('bulgarian-demo-chooser')).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.getByTestId('bulgarian-demo-chooser')).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByTestId('bulgarian-demo-chooser'));
    expect(screen.getByTestId('bulgarian-demo-chooser')).toBeInTheDocument();
    expect(apiPost).toHaveBeenCalledExactlyOnceWith('/v1/projects/demo/bulgaria', { template_id: 'residential' });
  });

  it('restores ordinary Escape dismissal after an installation fails', async () => {
    let rejectInstall!: (error: Error) => void;
    vi.mocked(apiPost).mockReturnValue(new Promise((_, reject) => { rejectInstall = reject; }));
    mount(<ProjectSwitcher />);
    fireEvent.click(screen.getByRole('button', { name: 'Switch Project' }));
    await screen.findByText('No projects yet');
    fireEvent.click(screen.getByRole('button', { name: 'bg_demo.explore' }));
    fireEvent.click(screen.getByTestId('bulgarian-demo-residential'));
    await waitFor(() => expect(screen.getByTestId('bulgarian-demo-residential')).toBeDisabled());
    await act(async () => { rejectInstall(new Error('Installation failed')); });
    await waitFor(() => expect(screen.getByTestId('bulgarian-demo-residential')).toBeEnabled());
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(screen.queryByTestId('bulgarian-demo-chooser')).toBeNull();
    expect(screen.getByRole('button', { name: 'bg_demo.explore' })).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(screen.queryByRole('button', { name: 'bg_demo.explore' })).toBeNull();
  });
});
