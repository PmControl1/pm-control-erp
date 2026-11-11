// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Browser-region detection stays available, while this product consistently
// offers Bulgarian setup and country-neutral learning examples.
//
// Run:  npx vitest run src/features/onboarding/__tests__/browserRegionDefaults.test.ts
import { afterEach, describe, expect, it } from 'vitest';

import {
  browserRegionForLanguage,
  detectBrowserRegion,
  detectCountry,
  detectCountryForLanguage,
} from '@/app/i18n';
import { countCasesByMarket, resolveHomeMarket } from '@/features/cases/marketCases';
import { PLAYBOOKS } from '@/features/cases/playbooks';

import { resolveCountryOffer } from '../countryOffer';
import { suggestDataSetup } from '../OnboardingWizard';

const REAL_LANGUAGE = navigator.language;
const REAL_LANGUAGES = navigator.languages;

function browser(language: string, languages: string[] = [language]): void {
  Object.defineProperty(window.navigator, 'language', { value: language, configurable: true });
  Object.defineProperty(window.navigator, 'languages', { value: languages, configurable: true });
}

afterEach(() => {
  Object.defineProperty(window.navigator, 'language', { value: REAL_LANGUAGE, configurable: true });
  Object.defineProperty(window.navigator, 'languages', { value: REAL_LANGUAGES, configurable: true });
});

/** The UI language a first run opens in for these browsers (what
 *  `resolveInitialLanguage` answers; pinned by firstRunLanguageKeepsTheRegion). */
const UI_LANGUAGE: Record<string, string> = {
  'en-CA': 'en',
  'fr-CA': 'fr',
  'en-US': 'en-US',
  'de-DE': 'de',
  'de-AT': 'de',
  'pt-BR': 'pt-BR',
  'en-NZ': 'en',
  'is-IS': 'en',
};

const MARKETS = [...countCasesByMarket(PLAYBOOKS).keys()].sort();

describe('the country a browser names', () => {
  it.each([
    ['en-CA', 'ca'],
    ['fr-CA', 'ca'],
    ['en-US', 'us'],
    ['de-DE', 'de'],
    ['de-AT', 'at'],
    ['pt-BR', 'br'],
    ['en-NZ', 'nz'],
    ['is-IS', 'is'],
  ])('%s names %s', (tag, country) => {
    browser(tag);
    expect(detectBrowserRegion()).toBe(country);
    expect(detectCountry()).toBe(country);
  });

  it('reads the region from a later entry in the same language', () => {
    browser('de', ['de', 'de-AT', 'en-US']);
    expect(detectBrowserRegion()).toBe('at');
  });

  it('does not borrow a region from another language further down the list', () => {
    browser('de', ['de', 'en-US']);
    expect(detectBrowserRegion()).toBeNull();
    expect(detectCountry('de')).toBe('de');
  });

  it("stops going by the browser once the reader picks another language", () => {
    browser('en-US');
    // en-US is the factory default of many machines far from the US, so a
    // reader who switches the app to German is read by their choice.
    expect(detectCountryForLanguage('de')).toBe('de');
    expect(browserRegionForLanguage('de')).toBeNull();
    browser('fr-CA');
    expect(detectCountryForLanguage('fr')).toBe('ca');
    expect(browserRegionForLanguage('fr')).toBe('ca');
  });
});

describe('the Bulgarian setup wizard defaults', () => {
  it.each(['en-CA', 'fr-CA', 'en-US', 'de-DE', 'pt-BR', 'en-NZ', 'de-AT', 'is-IS'])(
    'keeps Bulgarian setup for browser %s', (tag) => {
      browser(tag);
      expect(suggestDataSetup(detectCountry(), UI_LANGUAGE[tag] ?? 'en')).toEqual({
        region: 'BG_SOFIA', packId: 'bg',
      });
    },
  );

  it('offers the Bulgarian preset without a browser country', () => {
    expect(suggestDataSetup(null, 'en')).toEqual({ region: 'BG_SOFIA', packId: 'bg' });
    expect(resolveCountryOffer('bg', [])).toEqual({
      kind: 'preset', preset: expect.objectContaining({ id: 'bg', locale: 'bg' }),
    });
  });
});

describe('country-neutral cases across browser regions', () => {
  it.each(Object.keys(UI_LANGUAGE))('does not select a foreign case market for %s', (tag) => {
    browser(tag);
    const language = UI_LANGUAGE[tag]!;
    expect(MARKETS).toEqual([]);
    expect(resolveHomeMarket({
      language,
      browserRegion: browserRegionForLanguage(language),
      markets: MARKETS,
    })).toEqual({ market: null, source: null });
  });

  it('does not restore foreign examples from an old applied pack', () => {
    expect(resolveHomeMarket({
      language: 'en', packCountry: 'us', browserRegion: 'ca', markets: MARKETS,
    })).toEqual({ market: null, source: null });
  });
});
