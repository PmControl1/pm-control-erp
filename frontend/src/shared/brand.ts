// Product branding for this distribution.
//
// This build is a modified version of OpenConstructionERP
// (Copyright (c) 2026 Artem Boiko / DataDrivenConstruction, AGPL-3.0-or-later).
// Upstream's trademark policy (docs/legal/TRADEMARK.md) requires a modified,
// separately run product to carry its own name, so every user-facing product
// name and logo is read from here. Change the values below, and the files in
// /branding, to rebrand.

/** Product name shown in the UI, page titles, emails and exports. */
export const BRAND_NAME = 'PM Project Management';

/** Short form for tight spaces (PWA prompts, narrow headers). */
export const BRAND_SHORT_NAME = 'PM Project Management';

/** Logo served from frontend/public (copied there by branding/apply_branding.py). */
export const BRAND_LOGO_URL = '/brand/pmpm-logo.svg';

/** Where the in-app bug and support menus send email. Empty hides those entries. */
export const BRAND_SUPPORT_EMAIL = '';

/**
 * Public URL of THIS modified version's source code. AGPL-3.0 §13 requires
 * offering it to everyone who uses the app over a network. Fill it in (for
 * example your own GitHub repo) before giving access to anyone outside the
 * company.
 */
export const BRAND_SOURCE_URL = '';

/**
 * Upstream's own prompts: "Support us" / donation dialog, release news, the
 * "rate us" card. Off in this distribution. Typed as boolean (not the literal
 * false) so TypeScript keeps the guarded code reachable.
 */
export const UPSTREAM_PROMPTS_ENABLED: boolean = false;

/** Upstream project credited on the About page (nominative use, allowed by its trademark policy). */
export const UPSTREAM_NAME = 'OpenConstructionERP';
export const UPSTREAM_AUTHOR = 'Artem Boiko / DataDrivenConstruction';
export const UPSTREAM_SOURCE_URL = 'https://github.com/datadrivenconstruction/OpenConstructionERP';
