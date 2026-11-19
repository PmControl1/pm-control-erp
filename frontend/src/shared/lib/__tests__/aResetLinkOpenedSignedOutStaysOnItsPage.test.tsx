/**
 * A password-reset link is opened by someone who is signed out: that is why
 * they need it. A request on that page that gets a 401 (the partner-pack
 * branding request did) must not send them to the login page, where the
 * link's token is lost and the reset cannot be finished.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { usePartnerPack } from '@/shared/hooks/usePartnerPack';
import { useAuthStore } from '@/stores/useAuthStore';
import { apiGet, isSignedOutPage } from '../api';

const originalLocation = window.location;

function stubLocation(pathname: string): { pathname: string; href: string } {
  const location = { pathname, href: `http://localhost${pathname}` };
  Object.defineProperty(window, 'location', { value: location, writable: true, configurable: true });
  return location;
}

function answer401() {
  return vi.fn(
    async () =>
      new Response(JSON.stringify({ detail: 'Not authenticated' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      }),
  );
}

afterEach(() => {
  Object.defineProperty(window, 'location', { value: originalLocation, writable: true, configurable: true });
  vi.unstubAllGlobals();
});

describe('a sign-in page is never left because of a 401', () => {
  it.each(['/auth/reset', '/login', '/login-next', '/register', '/forgot-password', '/auth/oidc/callback'])(
    '%s is a page for signed-out people',
    (path) => expect(isSignedOutPage(path)).toBe(true),
  );

  it.each(['/', '/dashboard', '/projects/1/files', '/settings/auth'])('%s is not', (path) =>
    expect(isSignedOutPage(path)).toBe(false),
  );

  it('a 401 on the password-reset page leaves the person on it', async () => {
    const location = stubLocation('/auth/reset');
    vi.stubGlobal('fetch', answer401());
    await apiGet('/v1/partner-pack/current').catch(() => undefined);
    expect(location.href).toBe('http://localhost/auth/reset');
  });

  it('a 401 inside the app still goes to the login page', async () => {
    const location = stubLocation('/projects/1/files');
    vi.stubGlobal('fetch', answer401());
    await apiGet('/v1/projects/').catch(() => undefined);
    expect(location.href).toBe('/login');
  });
});

describe('the partner pack is asked for only when signed in', () => {
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
  }

  it('makes no request while signed out', async () => {
    useAuthStore.setState({ isAuthenticated: false });
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    renderHook(() => usePartnerPack(), { wrapper });
    await new Promise((r) => setTimeout(r, 50));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
