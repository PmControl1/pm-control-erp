/** Product defaults for PM Project Management's Bulgarian deployment. */
export const BULGARIAN_PROJECT_DEFAULTS = {
  region: 'BG',
  country_code: 'BG',
  currency: 'EUR',
  locale: 'bg',
} as const;

/** English remains available for partners and as the translation fallback. */
export const MARKET_UI_LANGUAGE_CODES: readonly string[] = ['bg', 'en'];
