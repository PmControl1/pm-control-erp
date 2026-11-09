// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// OpenConstructionERP — DataDrivenConstruction (DDC)
// Tests for first-run language selection: resolveInitialLanguage asks for the
// full browser code before stripping the region, and detectCountry reads a
// country from the region subtag or, failing that, from the resolved language.
import { afterEach, describe, expect, it } from 'vitest';

import { detectCountry, resolveInitialLanguage, SUPPORTED_LANGUAGES } from '../i18n';

const realLanguage = navigator.language;
const realLanguages = navigator.languages;

/**
 * Point navigator.language and localStorage at a clean first run.
 *
 * defineProperty rather than vi.spyOn: in jsdom `language` is an accessor on
 * Navigator.prototype, not an own property of the instance, and spyOn wants an
 * own descriptor.
 */
function firstRunWith(browserLanguage: string): void {
  Object.defineProperty(window.navigator, 'language', {
    value: browserLanguage,
    configurable: true,
  });
  // A real browser lists its language first in `languages`; jsdom's default
  // list is en-US whatever `language` says, and detectCountry reads the list.
  Object.defineProperty(window.navigator, 'languages', {
    value: [browserLanguage],
    configurable: true,
  });
  window.localStorage.clear();
  window.history.replaceState(null, '', '/');
}

afterEach(() => {
  Object.defineProperty(window.navigator, 'language', {
    value: realLanguage,
    configurable: true,
  });
  Object.defineProperty(window.navigator, 'languages', {
    value: realLanguages,
    configurable: true,
  });
  window.localStorage.clear();
});

describe('resolveInitialLanguage', () => {
  it('opens the Bulgarian product in Bulgarian regardless of browser market', () => {
    for (const browser of ['bg-BG', 'en-US', 'pt-BR', 'de-CH', 'is-IS']) {
      firstRunWith(browser);
      expect(resolveInitialLanguage()).toBe('bg');
    }
  });

  it('preserves an explicit Bulgarian or English choice', () => {
    for (const language of ['bg', 'en']) {
      firstRunWith('de-DE');
      window.localStorage.setItem('i18nextLng', language);
      expect(resolveInitialLanguage()).toBe(language);
    }
  });

  it('ignores a foreign language left over from the international product', () => {
    firstRunWith('de-DE');
    window.localStorage.setItem('i18nextLng', 'de');
    expect(resolveInitialLanguage()).toBe('bg');
  });
});

describe('detectCountry', () => {
  it('reads the region subtag when the browser sends one', () => {
    firstRunWith('pt-BR');
    expect(detectCountry()).toBe('br');
    firstRunWith('en-AU');
    expect(detectCountry()).toBe('au');
    firstRunWith('en-ZA');
    expect(detectCountry()).toBe('za');
  });

  it('reaches past a script subtag to the region behind it', () => {
    firstRunWith('zh-Hans-CN');
    expect(detectCountry()).toBe('cn');
  });

  it('falls back to the language country when the browser sends no region', () => {
    // The half that matters for Europe: a bare 'de' or 'pl' carries no region
    // at all, so region-only detection would answer null for most of the
    // continent. The language is passed explicitly so the fallback half is
    // deterministic rather than a property of whatever i18n booted into.
    firstRunWith('de');
    expect(detectCountry('de')).toBe('de');
    firstRunWith('pl');
    expect(detectCountry('pl')).toBe('pl');
    firstRunWith('ar');
    expect(detectCountry('ar')).toBe('sa');
    // And the one that surprises people: bare English names no country. It
    // used to answer 'gb', which read a preference out of a reader who had
    // expressed none. Now the two English entries that DO name a region
    // answer, and the unqualified one answers the code this codebase uses for
    // "not tied to a market" - which resolveCountryOffer already turns into no
    // offer, exactly as it does for null.
    firstRunWith('en');
    expect(detectCountry('en')).toBe('xx');
    expect(detectCountry('en-GB')).toBe('gb');
    expect(detectCountry('en-US')).toBe('us');
  });

  it('does not mistake a UN M49 region for a country code', () => {
    // es-419 is Latin America, not a country. Answering '41' or '419' would
    // be worse than answering the language's country.
    firstRunWith('es-419');
    expect(detectCountry('es')).toBe('es');
  });

  it('can name a country for every language we offer', () => {
    // The fallback half is only as good as the field it reads, and a new
    // language added without a country would make detectCountry answer null
    // for its readers without anything else going red.
    const missing = SUPPORTED_LANGUAGES.filter((l) => !l.country);
    expect(missing).toEqual([]);
  });
});
