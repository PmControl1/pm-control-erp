import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { normalizePackLocale } from '@/app/i18n';
import type { ClassificationOption, ProjectClassificationSpec } from '@/shared/hooks/usePartnerPack';
import { apiGet } from '@/shared/lib/api';

/**
 * The statutory classifications a project is filed under in its country.
 *
 * A country pack declares them (Bulgaria: the six ЗУТ categories of чл. 137)
 * and the server answers for a region and country with the list of the pack
 * that fits out that country, the same pack the project's rule sets and
 * methodology come from. The value is stored in `project.custom_fields[key]`
 * and the server refuses one that is not an option, so this field can only
 * offer what will be accepted.
 */
export interface ProjectClassificationsResponse {
  country: string | null;
  pack_slug: string | null;
  /** The pack's own language, which its labels are written in. */
  locale: string | null;
  source: string;
  classifications: ProjectClassificationSpec[];
}

export function projectClassificationsKey(region: string | null | undefined, country: string | null | undefined) {
  return ['project-classifications', region ?? '', (country ?? '').toUpperCase()] as const;
}

export function useProjectClassifications(region: string | null | undefined, country: string | null | undefined) {
  const hasInput = Boolean((region ?? '').trim() || (country ?? '').trim());
  return useQuery<ProjectClassificationsResponse>({
    queryKey: projectClassificationsKey(region, country),
    queryFn: () => {
      const params = new URLSearchParams();
      if (region) params.set('region', region);
      if (country) params.set('country', country);
      return apiGet<ProjectClassificationsResponse>(`/v1/partner-pack/project-classifications?${params.toString()}`);
    },
    enabled: hasInput,
    staleTime: 5 * 60_000,
  });
}

/**
 * Whether the reader reads the pack's own language.
 *
 * The labels are written in the market's language ("Категория по ЗУТ") with an
 * English gloss beside them. A Bulgarian reader gets the Bulgarian, everyone
 * else the gloss, and the original when no gloss was written.
 */
function readsPackLanguage(language: string, packLocale: string | null): boolean {
  if (!packLocale) return true;
  const base = (tag: string) => tag.toLowerCase().split('-')[0];
  return base(normalizePackLocale(packLocale)) === base(language);
}

export function classificationLabel(spec: ProjectClassificationSpec, own: boolean): string {
  return own ? spec.label : (spec.label_en ?? spec.label);
}

export function optionLabel(option: ClassificationOption, own: boolean): string {
  return own ? option.label : (option.label_en ?? option.label);
}

export function optionHint(option: ClassificationOption, own: boolean): string | null {
  return own ? option.hint : (option.hint_en ?? option.hint);
}

export function ProjectClassificationFields({
  idPrefix,
  region,
  countryCode,
  values,
  onChange,
  disabled = false,
  itemClassName,
}: {
  idPrefix: string;
  /** Class on each field's wrapper, e.g. a grid span. */
  itemClassName?: string;
  region: string | null | undefined;
  countryCode: string | null | undefined;
  /** The project's custom fields, or the draft of them on the create form. */
  values: Record<string, unknown> | null | undefined;
  onChange: (key: string, value: string | null) => void;
  disabled?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const { data } = useProjectClassifications(region, countryCode);
  const specs = data?.classifications ?? [];
  if (specs.length === 0) return null;
  const own = readsPackLanguage(i18n.language, data?.locale ?? null);

  return (
    <>
      {specs.map((spec) => {
        const id = `${idPrefix}-${spec.key}`;
        const hintId = `${id}-hint`;
        const raw = values?.[spec.key];
        const current = typeof raw === 'string' ? raw : '';
        const known = spec.options.find((option) => option.value === current) ?? null;
        const help = own ? spec.help : (spec.help_en ?? spec.help);
        const hint = known ? optionHint(known, own) : help;
        return (
          <div key={spec.key} className={itemClassName} data-testid={`project-classification-${spec.key}`}>
            <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-content-primary">
              {classificationLabel(spec, own)}
            </label>
            <select
              id={id}
              value={current}
              disabled={disabled}
              aria-describedby={hint || spec.statute ? hintId : undefined}
              onChange={(e) => onChange(spec.key, e.target.value === '' ? null : e.target.value)}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent disabled:opacity-60"
            >
              <option value="">{t('projects.classification.not_recorded', { defaultValue: 'Not recorded' })}</option>
              {spec.options.map((option) => (
                <option key={option.value} value={option.value}>
                  {optionLabel(option, own)}
                </option>
              ))}
              {current && !known && (
                // A value stored before the list changed is shown as it is, not
                // silently replaced; saving another clears it.
                <option value={current}>{current}</option>
              )}
            </select>
            {(hint || spec.statute) && (
              <p id={hintId} className="mt-1.5 text-xs text-content-tertiary">
                {hint}
                {spec.statute && (
                  <span className="block">
                    {t('projects.classification.statute', {
                      defaultValue: 'Set by {{statute}}',
                      statute: spec.statute,
                    })}
                  </span>
                )}
              </p>
            )}
          </div>
        );
      })}
    </>
  );
}
