// PM Project Management - the количествена сметка a КСС is priced against.
// Licensed under the GNU AGPL v3.0 or later, like the rest of this program.
/**
 * A Bulgarian КСС names the количествена сметка it was priced against, and the
 * `bulgaria.kss_matches_tender_bill` rule then compares the two line by line:
 * every description, unit and quantity kept, no line added. The link is the
 * bill's `metadata.kss_tender_bill_id`; the server merges metadata, so writing
 * the one key leaves the rest alone. Shown only on a project that runs the
 * bulgaria rule set (the Bulgaria pack, or a project in Bulgaria).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { useToastStore } from '@/stores/useToastStore';
import { boqApi } from './api';
import { editorErrorText } from './editorErrorText';

export const KSS_TENDER_BILL_KEY = 'kss_tender_bill_id';

interface ProjectLike {
  validation_rule_sets?: string[] | null;
  country_code?: string | null;
  region?: string | null;
}

/** Whether a project validates against the bulgaria rule set, the way the server decides it. */
export function runsBulgarianRules(project: ProjectLike | null | undefined): boolean {
  if (!project) return false;
  if ((project.validation_rule_sets ?? []).includes('bulgaria')) return true;
  if ((project.country_code ?? '').trim().toUpperCase() === 'BG') return true;
  const region = (project.region ?? '').trim().toUpperCase();
  return region === 'BG' || region === 'BULGARIA' || region.startsWith('BG_') || region.startsWith('BG-');
}

/** The tender bill a bill's metadata names, or ''. */
export function tenderBillId(metadata: Record<string, unknown> | null | undefined): string {
  const value = metadata?.[KSS_TENDER_BILL_KEY];
  return typeof value === 'string' ? value : '';
}

interface KssTenderBillPickerProps {
  boqId: string;
  projectId: string;
  metadata?: Record<string, unknown> | null;
  locked: boolean;
}

export function KssTenderBillPicker({ boqId, projectId, metadata, locked }: KssTenderBillPickerProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const current = tenderBillId(metadata);

  const { data: boqs } = useQuery({
    queryKey: ['boqs', projectId, 'kss-tender'],
    queryFn: async () => {
      const bills = [];
      const limit = 100;
      for (let offset = 0; ; offset += limit) {
        const page = await boqApi.list(projectId, { offset, limit });
        bills.push(...page);
        if (page.length < limit) return bills;
      }
    },
    enabled: !!projectId,
  });
  const choices = (boqs ?? []).filter((b) => b.id !== boqId);
  const known = !current || choices.some((b) => b.id === current);

  const save = useMutation({
    mutationFn: (value: string) => boqApi.update(boqId, { metadata: { [KSS_TENDER_BILL_KEY]: value || null } }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('boq.kss_tender_bill_failed', { defaultValue: 'Could not save the link' }),
        message: editorErrorText(err, t),
      });
    },
  });

  const hint = t('boq.kss_tender_bill_hint', {
    defaultValue:
      'The количествена сметка this КСС is priced against. Validation then checks that every description, unit and quantity is kept and that no line is added.',
  });

  return (
    <label className="flex min-w-0 items-center gap-2 text-xs text-content-secondary" title={hint}>
      <span className="whitespace-nowrap">{t('boq.kss_tender_bill', { defaultValue: 'Priced against' })}</span>
      <select
        value={current}
        disabled={locked || save.isPending}
        onChange={(e) => save.mutate(e.target.value)}
        data-testid="kss-tender-bill"
        aria-label={hint}
        className="min-w-0 max-w-[16rem] truncate rounded-md border border-border-light bg-surface-primary px-2 py-1 text-xs text-content-primary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30 disabled:opacity-60"
      >
        <option value="">{t('boq.kss_tender_bill_none', { defaultValue: 'None' })}</option>
        {!known && (
          <option value={current}>{t('boq.kss_tender_bill_gone', { defaultValue: 'No longer in this project' })}</option>
        )}
        {choices.map((b) => (
          <option key={b.id} value={b.id}>
            {b.name}
          </option>
        ))}
      </select>
    </label>
  );
}
