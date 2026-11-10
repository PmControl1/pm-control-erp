// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A language a person can pick for the interface must also be one they can pick
// for a project. Ukrainian was the case that was reported: offered in the
// header, missing from the project form, so the project went out as "other".

import { readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { PROJECT_LANGUAGES } from './projectLanguages';

const BACKEND_LOCALES = join(dirname(fileURLToPath(import.meta.url)), '../../../../backend/locales');

describe('project languages', () => {
  it('offers Bulgarian first and English as the fallback', () => {
    expect(PROJECT_LANGUAGES.map((language) => language.value)).toEqual(['bg', 'en']);
    expect(PROJECT_LANGUAGES[0]?.label).toBe('Български');
  });

  it('offers only languages the backend has a locale file for', () => {
    const files = new Set(readdirSync(BACKEND_LOCALES).map((f) => f.replace(/\.json$/, '')));
    const missing = PROJECT_LANGUAGES.map((l) => l.value).filter((c) => !files.has(c));
    expect(missing).toEqual([]);
  });

});
