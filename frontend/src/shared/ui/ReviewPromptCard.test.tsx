// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ReviewPromptCard - behaviour, not rendering.
 *
 * These tests seed `localStorage` the way a real browser would have it after
 * N days of use, re-read the store (which is what a page reload does) and
 * then mount the card. That path is the real one: the gate reads persisted
 * state on mount, so anything asserted here is what a user would actually
 * get.
 *
 * `react-i18next` and `localStorage` are mocked globally in `src/test/setup.ts`;
 * `t` returns the `defaultValue`, which is why the queries below match English
 * copy even though every string in the component is an i18n key.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

// Exercise the retained optional widget behavior without enabling upstream
// prompts in the PM Project Management distribution. The default-off contract
// is covered separately in pilotUpstreamPrompts.test.tsx.
vi.mock('@/shared/brand', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/brand')>();
  return { ...actual, UPSTREAM_PROMPTS_ENABLED: true };
});

import { ReviewPromptCard } from './ReviewPromptCard';
import {
  useReviewPromptStore,
  __resetReviewPromptStore,
  dayKey,
  REVIEW_PROMPT_CONSTANTS as C,
  type ReviewPromptState,
} from '@/stores/useReviewPromptStore';

const DAY = C.DAY_MS;
const CARD = 'review-prompt-card';

/** Write a state straight to storage, then reload the store from it. */
function seed(state: Partial<ReviewPromptState>): void {
  localStorage.setItem(
    C.STORAGE_KEY,
    JSON.stringify({
      firstSeenAt: null,
      activeDays: [],
      lastAskedAt: null,
      declineCount: 0,
      status: 'active',
      ...state,
    }),
  );
  __resetReviewPromptStore();
}

/** A browser that has cleared both earned-the-right gates. */
function seedEarnedIt(extra: Partial<ReviewPromptState> = {}): void {
  const now = Date.now();
  seed({
    firstSeenAt: now - 10 * DAY,
    activeDays: Array.from({ length: C.MIN_ACTIVE_DAYS }, (_, i) => dayKey(now - i * DAY)),
    ...extra,
  });
}

beforeEach(() => {
  localStorage.clear();
  __resetReviewPromptStore();
});

describe('ReviewPromptCard - when it may appear', () => {
  it('does not appear for a fresh user', () => {
    render(<ReviewPromptCard />);
    expect(screen.queryByTestId(CARD)).toBeNull();
  });

  it('does not appear for an install that is old but barely opened', () => {
    seed({ firstSeenAt: Date.now() - 30 * DAY, activeDays: ['2026-06-01', '2026-06-02'] });
    render(<ReviewPromptCard />);
    expect(screen.queryByTestId(CARD)).toBeNull();
  });

  it('does not appear for a busy user whose install is only two days old', () => {
    const now = Date.now();
    seed({
      firstSeenAt: now - 2 * DAY,
      activeDays: Array.from({ length: C.MIN_ACTIVE_DAYS }, (_, i) => dayKey(now - i * DAY)),
    });
    render(<ReviewPromptCard />);
    expect(screen.queryByTestId(CARD)).toBeNull();
  });

  it('appears once both thresholds are met', () => {
    seedEarnedIt();
    render(<ReviewPromptCard />);
    expect(screen.getByTestId(CARD)).toBeTruthy();
  });

  it('stays out of the way while the Support-us modal is still recent', () => {
    seedEarnedIt();
    localStorage.setItem(C.SUPPORT_MODAL_KEY, String(Date.now() - 1 * DAY));
    render(<ReviewPromptCard />);
    expect(screen.queryByTestId(CARD)).toBeNull();
  });
});

describe('ReviewPromptCard - it never blocks work', () => {
  it('is not a modal: no dialog role, no aria-modal, no backdrop', () => {
    seedEarnedIt();
    const { container } = render(<ReviewPromptCard />);
    const card = screen.getByTestId(CARD);
    expect(card.getAttribute('role')).toBe('region');
    expect(card.getAttribute('aria-modal')).toBeNull();
    expect(container.querySelector('[aria-modal="true"]')).toBeNull();
    // Nothing may lock the page behind it.
    expect(document.body.style.overflow).not.toBe('hidden');
  });

  it('does not steal focus when it appears', () => {
    seedEarnedIt();
    render(<ReviewPromptCard />);
    expect(document.activeElement).toBe(document.body);
  });
});

describe('ReviewPromptCard - cadence after an answer', () => {
  it('does not reappear immediately after "Maybe later"', () => {
    seedEarnedIt();
    const first = render(<ReviewPromptCard />);
    fireEvent.click(screen.getByText('Maybe later'));
    expect(screen.queryByTestId(CARD)).toBeNull();
    first.unmount();

    // Reload the page the same day.
    __resetReviewPromptStore();
    render(<ReviewPromptCard />);
    expect(screen.queryByTestId(CARD)).toBeNull();
  });

  it('does not reappear three days after a decline, but does after four', () => {
    seedEarnedIt();
    const asked = render(<ReviewPromptCard />);
    fireEvent.click(screen.getByText('Maybe later'));
    asked.unmount();

    const declined = useReviewPromptStore.getState().state;
    const now = Date.now();

    seed({ ...declined, lastAskedAt: now - 3 * DAY });
    const tooSoon = render(<ReviewPromptCard />);
    expect(screen.queryByTestId(CARD)).toBeNull();
    tooSoon.unmount();

    seed({ ...declined, lastAskedAt: now - 4 * DAY });
    render(<ReviewPromptCard />);
    expect(screen.getByTestId(CARD)).toBeTruthy();
  });

  it('pushes a second decline further out than the first', () => {
    const now = Date.now();
    // Four days was enough after ONE decline; it is not enough after two.
    seedEarnedIt({ declineCount: 2, lastAskedAt: now - 4 * DAY });
    const stillQuiet = render(<ReviewPromptCard />);
    expect(screen.queryByTestId(CARD)).toBeNull();
    stillQuiet.unmount();

    seedEarnedIt({ declineCount: 2, lastAskedAt: now - 14 * DAY });
    render(<ReviewPromptCard />);
    expect(screen.getByTestId(CARD)).toBeTruthy();
  });

  it('never appears again once the decline cap is hit', () => {
    // Literal 4, not C.MAX_DECLINES - see the matching note in the store
    // test. A cap read from the constant cannot detect the cap being raised.
    seedEarnedIt({ declineCount: 4, lastAskedAt: Date.now() - 365 * DAY });
    render(<ReviewPromptCard />);
    expect(screen.queryByTestId(CARD)).toBeNull();
  });
});

describe('ReviewPromptCard - terminal choices', () => {
  it('"Don\'t ask again" is permanent, even a year later', () => {
    seedEarnedIt();
    const first = render(<ReviewPromptCard />);
    fireEvent.click(screen.getByText("Don't ask again"));
    expect(screen.queryByTestId(CARD)).toBeNull();
    first.unmount();

    // Same browser, a year of heavy use later.
    const stored = useReviewPromptStore.getState().state;
    seed({ ...stored, lastAskedAt: Date.now() - 365 * DAY });
    render(<ReviewPromptCard />);
    expect(screen.queryByTestId(CARD)).toBeNull();
  });

  it('never asks again once the user has followed a review link', () => {
    seedEarnedIt();
    const first = render(<ReviewPromptCard />);
    fireEvent.click(screen.getByText('Star on GitHub'));
    expect(screen.queryByTestId(CARD)).toBeNull();
    first.unmount();

    const stored = useReviewPromptStore.getState().state;
    expect(stored.status).toBe('stopped');
    seed({ ...stored, lastAskedAt: Date.now() - 365 * DAY });
    render(<ReviewPromptCard />);
    expect(screen.queryByTestId(CARD)).toBeNull();
  });
});

describe('ReviewPromptCard - review destinations', () => {
  it('offers the confirmed review destinations, G2 included', () => {
    seedEarnedIt();
    render(<ReviewPromptCard />);
    const hrefs = Array.from(screen.getByTestId(CARD).querySelectorAll('a')).map((a) =>
      a.getAttribute('href'),
    );
    expect(hrefs.some((h) => h?.includes('github.com/datadrivenconstruction'))).toBe(true);
    expect(hrefs.some((h) => h?.includes('linkedin.com'))).toBe(true);

    const g2 = hrefs.find((h) => h?.includes('g2.com'));
    expect(g2).toBe('https://www.g2.com/products/openconstructionerp/reviews');
    // "?source=search" is G2's search-result tracking. It must never ride
    // along on a link we hand to a user.
    expect(g2).not.toContain('source=search');
    // Every link opens away from the app, so work in progress is never lost.
    Array.from(screen.getByTestId(CARD).querySelectorAll('a')).forEach((a) => {
      expect(a.getAttribute('target')).toBe('_blank');
      expect(a.getAttribute('rel')).toContain('noopener');
    });
  });
});

describe('ReviewPromptCard - storage disabled', () => {
  it('renders nothing and does not crash when localStorage throws', () => {
    const original = Object.getOwnPropertyDescriptor(window, 'localStorage');
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: () => {
          throw new Error('blocked');
        },
        setItem: () => {
          throw new Error('blocked');
        },
        removeItem: () => {},
        clear: () => {},
      },
    });

    __resetReviewPromptStore();
    expect(() => render(<ReviewPromptCard />)).not.toThrow();
    expect(screen.queryByTestId(CARD)).toBeNull();

    if (original) Object.defineProperty(window, 'localStorage', original);
  });
});
