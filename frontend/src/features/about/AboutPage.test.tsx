import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AboutPage } from './AboutPage';
import { BRAND_NAME, UPSTREAM_SOURCE_URL } from '@/shared/brand';

const mode = vi.hoisted(() => ({ internal: false }));
vi.mock('@/shared/brand', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/shared/brand')>(),
  get TEST_BUILD() { return mode.internal; },
}));

afterEach(cleanup);

describe('About page build modes', () => {
  it.each([false, true])('renders the product identity and gates notices (internal: %s)', (internal) => {
    mode.internal = internal;
    const { container } = render(<MemoryRouter><AboutPage /></MemoryRouter>);
    expect(screen.getByRole('heading', { name: BRAND_NAME })).toBeInTheDocument();
    const credit = container.querySelector('[data-upstream-credit]');
    const changelog = container.querySelector('[data-changelog-anchor]');
    expect(changelog).toBeInTheDocument();
    if (internal) {
      fireEvent.click(screen.getByRole('button', { name: 'Show full history' }));
      expect(screen.getByRole('button', { name: 'Show less' })).toBeInTheDocument();
      expect(credit).toBeNull();
      expect(container).not.toHaveTextContent(/AGPL|DataDrivenConstruction|OpenConstruction|third.party software|YouTube|academy videos|\blicen[cs](?:e|ing)/i);
    } else {
      expect(credit).toHaveAttribute('href', UPSTREAM_SOURCE_URL);
      expect(container).toHaveTextContent('AGPL-3.0');
    }
  });
});
