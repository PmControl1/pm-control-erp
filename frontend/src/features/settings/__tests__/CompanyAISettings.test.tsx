import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { AIConfigurationCard } from '../SettingsPage';

const { readPersonal, read, put, post } = vi.hoisted(() => ({
  readPersonal: vi.fn(), read: vi.fn(), put: vi.fn(), post: vi.fn(),
}));
vi.mock('@/features/ai/api', async (original) => {
  const actual = await original<typeof import('@/features/ai/api')>();
  return { ...actual, aiApi: { ...actual.aiApi, getSettings: readPersonal } };
});
vi.mock('@/shared/lib/api', async (original) => {
  const actual = await original<typeof import('@/shared/lib/api')>();
  return { ...actual, apiGet: read, apiPut: put, apiPost: post };
});

const configPath = '/v1/ai/company/settings/';
const teamsPath = '/v1/ai/internal-pilot/teams/';
const current = { provider: 'deepseek', model: 'pilot-model', key_set: true };
const sampleTeam = {
  id: 'team-1', name: 'Supervision', project_name: 'Pilot site', active: true,
  approved_members: 1, eligible_members: 2, pending_members: 1, enabled: true,
};
function renderSettings(isOwner: boolean, hasAccess: boolean) {
  readPersonal.mockResolvedValue({
    default_models: { openai: 'production-model' },
    managed_ai: { is_owner: isOwner, has_access: hasAccess, configured: true, provider: 'deepseek', model: 'pilot-model' },
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter><AIConfigurationCard /></MemoryRouter></QueryClientProvider>);
}

afterEach(cleanup);

beforeEach(() => {
  vi.resetAllMocks();
  read.mockImplementation(async (path: string) => path === configPath ? current : { teams: [sampleTeam] });
});

describe('company AI settings', () => {
  it.each([true, false])('shows managed status without credential controls or owner requests (access %s)', async (allowed) => {
    renderSettings(false, allowed);
    expect(await screen.findByRole('status')).toHaveTextContent(allowed ? /Your team can use/ : /unavailable/);
    expect(screen.queryByLabelText(/API key/i)).toBeNull();
    expect(screen.queryByLabelText(/Company provider/i)).toBeNull();
    expect(read).not.toHaveBeenCalled();
  });

  it('uses the saved connection for testing; a provider switch clears the key and requires a fresh one', async () => {
    put.mockResolvedValue({ provider: 'openai', model: 'production-model', key_set: true });
    post.mockResolvedValue({ success: true });
    renderSettings(true, true);
    fireEvent.click(await screen.findByRole('button', { name: 'Test saved connection' }));
    expect(await screen.findByRole('status')).toHaveTextContent('The saved connection works.');
    expect(post).toHaveBeenCalledWith(configPath + 'test/');
    const key = screen.getByLabelText('Company API key');
    fireEvent.change(key, { target: { value: 'other-provider-example' } });
    fireEvent.change(screen.getByLabelText('Company provider'), { target: { value: 'openai' } });
    expect(key).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Test saved connection' })).toBeDisabled();
    fireEvent.change(key, { target: { value: 'new-example' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(put).toHaveBeenCalledWith(configPath, {
      provider: 'openai', model: 'production-model', api_key: 'new-example',
    }));
    await waitFor(() => expect(screen.getByLabelText('Company API key')).toHaveValue(''));
  });

  it('can change the model without resending a key', async () => {
    put.mockResolvedValue({ ...current, model: 'next-model' });
    renderSettings(true, true);
    fireEvent.change(await screen.findByLabelText('Model ID'), { target: { value: 'next-model' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(put).toHaveBeenCalledWith(configPath, { provider: 'deepseek', model: 'next-model' }));
  });

  it.each([['Approve new members', true], ['Revoke access', false], ['Grant access', true]] as const)(
    '%s applies just to the selected project team', async (label, enabled) => {
      const team = { ...sampleTeam, enabled: label !== 'Grant access' };
      read.mockImplementation(async (path: string) => path === configPath ? current : { teams: [team] });
      put.mockResolvedValue({ ...team, enabled });
      renderSettings(true, true);
      fireEvent.click(await screen.findByRole('button', { name: label }));
      await waitFor(() => expect(put).toHaveBeenCalledWith(teamsPath + 'team-1', { enabled }));
    });
});
