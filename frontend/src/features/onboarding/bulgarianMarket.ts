import type { BaseCatalog } from '@/features/costs/baseCatalog';

/** Only the Bulgarian country configuration is selectable in this product. */
export const BULGARIAN_PACK_SLUG = 'bulgaria-bg';

export function bulgarianCountryPacks<T extends { slug: string }>(packs: readonly T[]): T[] {
  return packs.filter((pack) => pack.slug === BULGARIAN_PACK_SLUG);
}

/** Ignore foreign setup options returned by an older server or cached response. */
export function bulgarianBaseCatalog(catalog: BaseCatalog): BaseCatalog {
  const families = catalog.families.map((family) => {
    const variants = family.variants.filter((variant) =>
      variant.region === 'BG_SOFIA' &&
      variant.base_region === 'BG_SOFIA' &&
      !variant.market_catalog,
    );
    return {
      ...family,
      variants,
      market_count: variants.length,
      loaded_count: variants.filter((variant) => variant.loaded).length,
      repriceable_markets: 0,
    };
  }).filter((family) => family.variants.length > 0);
  return {
    ...catalog,
    families,
    total_families: families.length,
    total_bases: families.reduce((count, family) => count + family.variants.length, 0),
    loaded_regions: catalog.loaded_regions.filter((region) => region === 'BG_SOFIA'),
  };
}
