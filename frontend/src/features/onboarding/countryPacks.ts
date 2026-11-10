// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Bulgarian workspace setup preset. Shared pack types remain available to the installer. */

/** Cost-classification standard a Country Pack records for the workspace. */
export type ClassificationStandard =
  | 'DIN276'
  | 'NRM'
  | 'MasterFormat'
  | 'CCS'
  | 'CWICR'
  | 'КСС';

/** A single curated Country Pack preset. */
export interface CountryPack {
  /** Stable id, kebab-case, used as React key + analytics tag. */
  id: string;
  /** Display label for the country / market (English default value). */
  labelKey: string;
  /** Fallback English label, used as the i18next ``defaultValue``. */
  labelDefault: string;
  /** CountryFlag code (ISO-3166 alpha-2, lowercase). */
  flagId: string;
  /** UI language code (i18next). */
  locale: string;
  /** CWICR cost-database id — must exist in ``CWICR_DATABASES``. */
  region: string;
  /**
   * Demo project id, a key of the backend ``DEMO_TEMPLATES``.
   *
   * Not nullable, and deliberately so. A preset whose demo is missing is a
   * preset that quietly under-delivers what its own subtitle promises, which
   * is how sixteen markets ended up shipping without an example project. The
   * compiler now refuses that shape, and the backend test refuses an id the
   * registry cannot resolve.
   */
  demoId: string;
  /** Cost-classification standard recorded for the workspace. */
  classification: ClassificationStandard;
}

/** The market is fixed for this Bulgarian product. */
export const DEFAULT_COUNTRY_PACK: CountryPack = {
  id: 'bg',
  labelKey: 'onboarding.pack_bg',
  labelDefault: 'Bulgaria',
  flagId: 'bg',
  locale: 'bg',
  region: 'BG_SOFIA',
  demoId: 'residential-sofia',
  classification: 'КСС',
};

export const COUNTRY_PACKS: CountryPack[] = [DEFAULT_COUNTRY_PACK];
export type CountryPackId = (typeof COUNTRY_PACKS)[number]['id'];

export function getCountryPack(id: string): CountryPack | undefined {
  return COUNTRY_PACKS.find((pack) => pack.id === id);
}
