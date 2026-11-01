import { act, cleanup, render } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SupportUsButton } from '@/app/layout/SupportUsButton';
import { UPSTREAM_PROMPTS_ENABLED } from '@/shared/brand';
import {
  __resetReviewPromptStore,
  dayKey,
  REVIEW_PROMPT_CONSTANTS as C,
  useReviewPromptStore,
} from '@/stores/useReviewPromptStore';
import { ReviewPromptCard } from '../ReviewPromptCard';
import {
  CheckForUpdatesButton,
  UpdateBadge,
  UpdateInlineNotice,
  UpdateNotification,
} from '../UpdateChecker';

// Keep the real brand module: behavior suites explicitly enable optional
// upstream widgets, while these tests pin what the pilot actually ships.
const clients: QueryClient[] = [];

beforeEach(() => {
  localStorage.clear();
  __resetReviewPromptStore();
});

afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.unstubAllGlobals();
});

describe('PM Project Management upstream prompts', () => {
  it('keeps support and review prompts hidden even when their cadence permits them', async () => {
    expect(UPSTREAM_PROMPTS_ENABLED).toBe(false);
    const now = Date.now();
    const saved = JSON.stringify({
      firstSeenAt: now - 30 * C.DAY_MS,
      activeDays: Array.from({ length: C.MIN_ACTIVE_DAYS }, (_, i) => dayKey(now - i * C.DAY_MS)),
      lastAskedAt: null,
      declineCount: 0,
      status: 'active',
    });
    localStorage.setItem(C.STORAGE_KEY, saved);
    __resetReviewPromptStore();
    // An eligible store can already be visible when the shell mounts.
    useReviewPromptStore.setState({ visible: true });
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    clients.push(client);
    let container!: HTMLElement;
    await act(async () => {
      ({ container } = render(
        <QueryClientProvider client={client}>
          <MemoryRouter>
            <SupportUsButton />
            <SupportUsButton condensed />
            <ReviewPromptCard />
          </MemoryRouter>
        </QueryClientProvider>,
      ));
    });

    expect(container).toBeEmptyDOMElement();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(localStorage.getItem(C.STORAGE_KEY)).toBe(saved);
    expect(localStorage.getItem(C.SUPPORT_MODAL_KEY)).toBeNull();
  });

  it.each([false, true])('hides every update control without fetching (cached update: %s)', async (cached) => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    clients.push(client);
    if (cached) {
      client.setQueryData(['system-version-check'], {
        current_version: '18.1.0',
        latest_version: '18.2.0',
        update_available: true,
        release_url: 'https://github.com/datadrivenconstruction/OpenConstructionERP/releases',
        release_notes: 'An upstream release cached before rebranding.',
        published_at: '',
        assets: [],
        self_upgrade_supported: true,
        upgrade_command: 'pip install --upgrade openconstructionerp',
      });
    }

    let container!: HTMLElement;
    await act(async () => {
      ({ container } = render(
        <QueryClientProvider client={client}>
          <MemoryRouter>
            <CheckForUpdatesButton />
            <UpdateBadge />
            <UpdateInlineNotice />
            <UpdateNotification />
          </MemoryRouter>
        </QueryClientProvider>,
      ));
    });

    expect(container).toBeEmptyDOMElement();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
