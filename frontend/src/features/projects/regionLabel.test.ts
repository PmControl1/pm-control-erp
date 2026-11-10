// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { regionOptionLabel } from './regionLabel';
import { getCountry } from '@/shared/lib/countries';
import projectPageSource from './CreateProjectPage.tsx?raw';

// P-55: a Croatian estimator looked for "Hrvatska" in the region list and
// found only the English "Croatia".
describe('regionOptionLabel', () => {
  const croatia = { value: 'Croatia', label: 'Croatia', iso: 'HR' };

  it('names a single-country region in the reader language', () => {
    expect(regionOptionLabel(croatia, 'hr')).toBe('Hrvatska');
    expect(regionOptionLabel(croatia, 'de')).toBe('Kroatien');
    expect(regionOptionLabel(croatia, 'en')).toBe('Croatia');
  });

  it('keeps the label of a grouping that is not one country', () => {
    const dach = { value: 'DACH', label: 'DACH (Germany, Austria, Switzerland)' };
    expect(regionOptionLabel(dach, 'hr')).toBe('DACH (Germany, Austria, Switzerland)');
  });

  it('falls back to the label for an unknown language tag', () => {
    expect(regionOptionLabel(croatia, '')).toBe('Croatia');
  });
});

// The Bulgarian product's selector offers one region, Bulgaria, keyed by its
// ISO code. Check the shipped options, not test fixtures.
describe('the Bulgarian project region', () => {
  it('is the only option, named in Bulgarian for a Bulgarian reader', () => {
    const block = projectPageSource.split('const REGION_GROUPS')[1]?.split('\n];')[0] ?? '';
    const options = [...block.matchAll(/value: '([^']+)', label: '([^']+)', iso: '([^']+)'/g)]
      .map((match) => ({ value: match[1]!, label: match[2]!, iso: match[3]! }));
    expect(options).toHaveLength(1);
    const option = options[0];
    if (!option) throw new Error('Missing region option BG');
    expect(option.value).toBe('BG');
    expect(option.iso).toBe('BG');
    expect(option.label).toBe(getCountry('BG')?.name);
    expect(regionOptionLabel(option, 'bg')).toBe('България');
    expect(regionOptionLabel(option, 'en')).toBe('Bulgaria');
  });
});
