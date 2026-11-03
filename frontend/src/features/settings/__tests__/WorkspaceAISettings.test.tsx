import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import type { WorkspaceAIStatus } from '@/features/ai/workspaceAi';

const state = vi.hoisted(() => ({
  status: undefined as WorkspaceAIStatus | undefined,
  save: vi.fn(),
}));

vi.mock('@/features/ai/workspaceAi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/ai/workspaceAi')>();
  return {
    ...actual,
    useWorkspaceAI: () => ({ data: state.status }),
    workspaceAiApi: { ...actual.workspaceAiApi, save: state.save },
  };
});

import { WorkspaceAISection } from '../WorkspaceAISettings';
import { SettingsPage } from '../SettingsPage';

function renderSettings() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><WorkspaceAISection /></QueryClientProvider>);
}

beforeEach(() => {
  state.status = undefined;
  state.save.mockReset();
});
afterEach(cleanup);

describe('workspace AI visibility', () => {
  it.each([undefined, { configured: true, memory_enabled: false, can_manage: false }])(
    'does not mount personal provider settings or diagnostics before access is established: %j',
    (status) => {
      state.status = status;
      const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
      client.setQueryData(['me'], { id: 'member', full_name: 'Employee', email: 'member@test.io' });
      render(
        <MemoryRouter initialEntries={['/settings?tab=ai']}>
          <QueryClientProvider client={client}><SettingsPage /></QueryClientProvider>
        </MemoryRouter>,
      );
      expect(screen.queryByText('AI Configuration')).toBeNull();
      expect(screen.queryByLabelText('AI Provider')).toBeNull();
      expect(screen.queryByText('Semantic search')).toBeNull();
    },
  );

  it('shows employees readiness without provider, model or configuration controls', () => {
    state.status = { configured: true, memory_enabled: false, can_manage: false };
    const page = renderSettings();

    expect(screen.getByText('AI is ready to use')).toBeVisible();
    expect(screen.getByText('Your workspace provides AI. There is nothing to set up.')).toBeVisible();
    expect(page.container.querySelector('input, select')).toBeNull();
    expect(screen.queryByRole('button', { name: /Save|Test Connection|Turn off/ })).toBeNull();
  });

  it('does not display provider details from an obsolete cached member response', () => {
    state.status = {
      configured: true, memory_enabled: false, can_manage: false,
      provider: 'deepseek', model: 'deepseek-private-model', system_prompt: 'Private owner instructions',
    };
    const page = renderSettings();
    expect(page.container.textContent).not.toMatch(/deepseek|Private owner instructions/i);
  });

  it('keeps the owner able to review and change the shared model without re-entering the key', async () => {
    state.status = {
      configured: true, memory_enabled: false, can_manage: true,
      provider: 'deepseek', model: 'deepseek-private-model', providers: ['deepseek', 'openai'],
      default_models: { deepseek: 'deepseek-flash' }, key_set: true, key_hint: '…1234',
      system_prompt: 'Answer in Bulgarian.',
    };
    state.save.mockResolvedValue(state.status);
    renderSettings();

    const model = screen.getByLabelText('Model');
    expect(model).toHaveValue('deepseek-private-model');
    expect(screen.getByLabelText('AI Provider')).toHaveValue('deepseek');
    expect(screen.getByLabelText('API Key')).toHaveValue('');
    fireEvent.change(model, { target: { value: 'owner-selected-model' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(state.save).toHaveBeenCalledWith({
      provider: 'deepseek', model: 'owner-selected-model', api_key: undefined,
      system_prompt: 'Answer in Bulgarian.', memory_enabled: false,
    }));
  });
});
