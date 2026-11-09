import { afterEach, describe, expect, it } from 'vitest';
import i18n from '@/app/i18n';
import { numberLocaleForCountry, resolveNumberLocale } from '@/stores/usePreferencesStore';
import { getMarketNumberLocale, setMarketNumberLocale } from './marketNumberLocale';

const originalMarket = getMarketNumberLocale();
const originalLanguage = i18n.language;
afterEach(async () => {
  setMarketNumberLocale(originalMarket);
  await i18n.changeLanguage(originalLanguage);
});

describe('Bulgarian document number formatting', () => {
  it('keeps Bulgarian separators when the interface is in English', async () => {
    await i18n.changeLanguage('en');
    setMarketNumberLocale(numberLocaleForCountry('BG'));
    const formatted = new Intl.NumberFormat(resolveNumberLocale('auto')).format(1234.56);
    expect(formatted).toBe(new Intl.NumberFormat('bg-BG').format(1234.56));
    expect(formatted).toContain(',56');
  });

  it('preserves a deliberately selected format', () => {
    setMarketNumberLocale(numberLocaleForCountry('BG'));
    expect(resolveNumberLocale('en-US')).toBe('en-US');
  });
});
