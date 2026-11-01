// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Configured report channels work on both builds; the pilot keeps reports
 * local when its issue tracker has not been configured.
 *
 * Reported against 18.5.0 as "none of the links work". Two things in this menu
 * made that true without any link being broken on its own:
 *
 *  - the e-mail channel assigned `window.location.href = 'mailto:...'`, which
 *    the desktop webview does not hand to a mail client, so it did nothing;
 *  - while the recent errors were only network blips, the whole channel list
 *    sat under `opacity-40 pointer-events-none`. The desktop app logs a few of
 *    those on every start while its server comes up, so the menu read as a
 *    column of dead links until somebody found "report anyway".
 *
 * `openLink` is the one place that knows how to open a link on each build (see
 * desktop.test.ts), so here it is observed rather than exercised.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const openLink = vi.hoisted(() => vi.fn());
const networkOnly = vi.hoisted(() => ({ value: false }));
const copyToClipboard = vi.hoisted(() => vi.fn().mockResolvedValue(true));

// A distribution's own address may be configured without re-enabling any
// upstream destination. The default empty-address case has its own suite.
vi.mock('@/shared/brand', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/shared/brand')>(),
  BRAND_SUPPORT_EMAIL: 'support@example.test',
}));

vi.mock('@/shared/lib/browser', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/shared/lib/browser')>(),
  copyToClipboard,
}));

vi.mock('@/shared/lib/desktop', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/desktop')>();
  return { ...actual, openLink };
});

vi.mock('@/shared/lib/errorLogger', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/errorLogger')>();
  return { ...actual, isLastErrorNetworkOnly: () => networkOnly.value };
});

import { BugReportMenu } from './Header';

const REAL_DESCRIPTION =
  'I clicked Install on the UK JCT pack on the modules page and nothing happened.';

function openMenu() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <BugReportMenu />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByLabelText('Report a bug or send feedback'));
  fireEvent.change(screen.getByLabelText(/What happened/), { target: { value: REAL_DESCRIPTION } });
}

const channel = (label: string) => screen.getByText(label).closest('button') as HTMLButtonElement;

describe('bug menu channels', () => {
  beforeEach(() => {
    openLink.mockClear();
    copyToClipboard.mockClear();
    networkOnly.value = false;
  });

  it('sends the e-mail channel through openLink, not a webview navigation', () => {
    openMenu();
    fireEvent.click(channel('Email the team'));

    expect(openLink).toHaveBeenCalledTimes(1);
    const url = openLink.mock.calls[0]![0] as string;
    expect(url.startsWith('mailto:support@example.test?subject=')).toBe(true);
    expect(decodeURIComponent(url)).toContain(REAL_DESCRIPTION);
  });

  it('does not offer the upstream web form when a distribution configures its own email', () => {
    openMenu();

    expect(screen.queryByText('Web feedback form')).toBeNull();
    expect(openLink).not.toHaveBeenCalled();
  });

  it('keeps every channel usable while the network banner is showing', () => {
    networkOnly.value = true;
    openMenu();

    // The banner is still there to explain, it just no longer locks the menu.
    expect(screen.getByRole('alert')).toBeTruthy();
    const list = channel('Email the team').parentElement as HTMLElement;
    expect(list.className).not.toMatch(/pointer-events-none|opacity-40/);

    fireEvent.click(channel('Email the team'));
    fireEvent.click(screen.getByLabelText('Report a bug or send feedback'));
    fireEvent.change(screen.getByLabelText(/What happened/), { target: { value: REAL_DESCRIPTION } });
    fireEvent.click(channel('Report a bug (with logs)'));

    expect(openLink).toHaveBeenCalledTimes(1);
    expect(copyToClipboard).toHaveBeenCalledTimes(1);
    expect(copyToClipboard).toHaveBeenCalledWith(expect.stringContaining(REAL_DESCRIPTION));
  });
});
