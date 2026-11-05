import { describe, expect, it } from 'vitest';

import { baseLanguage, distinctTags, keyLanguage, languageTag, preferLanguage } from '../contentLanguage';
import { validationSummary } from '../RegionalPackCard';
import { DASHBOARD_WIDGET_BY_ID } from '../widgetRegistry';

describe('languageTag', () => {
  it('prints nothing for content in the UI language, regional variants included', () => {
    expect(languageTag('de', 'de')).toBeNull();
    expect(languageTag('pt', 'pt-BR')).toBeNull();
  });

  it('prints the base code of foreign content', () => {
    expect(languageTag('en', 'bg')).toBe('EN');
    expect(languageTag('de-AT', 'bg')).toBe('DE');
    expect(languageTag('', 'bg')).toBeNull();
    expect(baseLanguage('zh_Hans')).toBe('zh');
  });
});

describe('keyLanguage', () => {
  const store: Record<string, Record<string, string>> = { bg: { 'cases.a.title': 'Заглавие' } };
  const i18n = {
    language: 'bg',
    getResource: (lng: string, _ns: string, key: string) => store[lng]?.[key],
  };

  it('is the UI language when the key is translated there, else English', () => {
    expect(keyLanguage(i18n, 'cases.a.title')).toBe('bg');
    expect(keyLanguage(i18n, 'cases.b.title')).toBe('en');
  });

  it('follows the lookup chain, so a regional locale is not tagged for keys its base carries', () => {
    const chained = {
      language: 'pt-BR',
      languages: ['pt-BR', 'pt', 'en'],
      getResource: (lng: string, _ns: string, key: string) =>
        (
          {
            pt: { 'cases.a.title': 'Título' },
            en: { 'cases.a.title': 'Title', 'cases.b.title': 'Other' },
          } as Record<string, Record<string, string>>
        )[lng]?.[key],
    };
    expect(keyLanguage(chained, 'cases.a.title')).toBe('pt');
    expect(languageTag(keyLanguage(chained, 'cases.a.title'), chained.language)).toBeNull();
    expect(languageTag(keyLanguage(chained, 'cases.b.title'), chained.language)).toBe('EN');
  });

  it('falls back to the UI language and its base when i18next exposes no chain', () => {
    const plain = {
      language: 'de-AT',
      getResource: (lng: string, _ns: string, key: string) => (lng === 'de' && key === 'k' ? 'Wert' : undefined),
    };
    expect(keyLanguage(plain, 'k')).toBe('de');
    expect(keyLanguage(plain, 'missing')).toBe('en');
  });
});

describe('distinctTags', () => {
  it('lists each tag once, in first-seen order, skipping tiles in the UI language', () => {
    expect(distinctTags([null, 'EN', 'DE', 'EN', null])).toEqual(['EN', 'DE']);
    expect(distinctTags([null, null])).toEqual([]);
  });
});

describe('preferLanguage', () => {
  it('puts the reader language first, keeps order, drops nothing', () => {
    const items = [
      { id: 1, lang: 'en' },
      { id: 2, lang: 'bg' },
      { id: 3, lang: 'de' },
      { id: 4, lang: 'bg' },
    ];
    expect(preferLanguage(items, (i) => i.lang, 'bg').map((i) => i.id)).toEqual([2, 4, 1, 3]);
  });
});

describe('validationSummary', () => {
  it('names one standard, counts several, ticks the generic checks alone', () => {
    expect(validationSummary([]).kind).toBe('none');
    expect(validationSummary(['boq_quality']).kind).toBe('tick');
    expect(validationSummary(['din276', 'boq_quality'])).toEqual({ kind: 'single', standards: ['din276'] });
    expect(validationSummary(['din276', 'gaeb', 'boq_quality']).kind).toBe('many');
  });
});

describe('dashboard layout of the pack and the market cases', () => {
  it('stacks both cards at full width so neither is stretched beside the other', () => {
    expect(DASHBOARD_WIDGET_BY_ID.regional_pack?.defaultSpan).toBe(6);
    expect(DASHBOARD_WIDGET_BY_ID.cases_market?.defaultSpan).toBe(6);
  });
});
