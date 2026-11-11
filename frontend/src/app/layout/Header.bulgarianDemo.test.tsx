import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
  it('lets a viewer with no projects open their demo from the global picker', async () => {
    vi.mocked(apiPost).mockImplementation(async () => {
      vi.mocked(fetchProjectList).mockResolvedValue([{ id: 'own-demo', name: 'ДЕМО' }]);
      return { project_id: 'own-demo', project_name: 'ДЕМО', already_installed: false };
    });
    mount(<ProjectSwitcher />);
    fireEvent.click(screen.getByRole('button', { name: 'Switch Project' }));
    await screen.findByText('No projects yet');
    fireEvent.click(within(screen.getByTestId('header-project-picker')).getByRole('button', { name: 'bg_demo.explore' }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/projects/own-demo'));
    expect(apiPost).toHaveBeenCalledExactlyOnceWith('/v1/projects/demo/bulgaria', {});
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

  it('lets a viewer with no projects open the demo from the chat project selector', async () => {
    vi.mocked(apiPost).mockResolvedValue({ project_id: 'chat-demo', project_name: 'ДЕМО', already_installed: true });
    mount(<ProjectSelector />);
    fireEvent.click(screen.getByRole('button', { name: /All Projects/ }));
    await screen.findByText('No projects');
    fireEvent.click(screen.getByRole('button', { name: 'bg_demo.explore' }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/projects/chat-demo'));
    expect(useProjectContextStore.getState().activeProjectId).toBe('chat-demo');
    expect(screen.queryByRole('button', { name: 'bg_demo.explore' })).toBeNull();
  });

  it('keeps the chat demo launcher visible while its project list is loading', () => {
    vi.mocked(fetchProjectList).mockReturnValue(new Promise(() => {}));
    mount(<ProjectSelector />);
    fireEvent.click(screen.getByRole('button', { name: /All Projects/ }));
    expect(screen.getByRole('button', { name: 'bg_demo.explore' })).toBeEnabled();
  });
});
