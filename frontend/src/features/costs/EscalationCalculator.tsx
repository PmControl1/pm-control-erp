// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { TrendingUp, Calculator, Info } from 'lucide-react';
import clsx from 'clsx';
import { fmtPercent, fmtFixed } from '@/shared/lib/formatters';
import { getNumberLocale } from '@/stores/usePreferencesStore';

// Annual escalation is supplied by the estimator. No foreign index is
// substituted for Bulgarian project data.

const YEARS = Array.from({ length: 11 }, (_, i) => 2020 + i); // 2020-2030

interface EscalationCalculatorProps {
  /** Base amount to escalate */
  baseAmount?: number;
  /** Callback when escalated amount is computed */
  onApply?: (escalatedAmount: number, factor: number) => void;
  className?: string;
}

export function EscalationCalculator({
  baseAmount: propBaseAmount,
  onApply,
  className,
}: EscalationCalculatorProps) {
  const { t } = useTranslation();
  const [baseYear, setBaseYear] = useState(2023);
  const [targetYear, setTargetYear] = useState(2026);
  const [manualRate, setManualRate] = useState<string>('');
  const [amount, setAmount] = useState(propBaseAmount?.toString() ?? '100000');

  const baseAmountNum = useMemo(() => Number(amount), [amount]);
  const annualRate = Number(manualRate);
  const validRate = manualRate.trim() !== '' && Number.isFinite(annualRate) && annualRate >= -100;
  const validAmount = amount.trim() !== '' && Number.isFinite(baseAmountNum) && baseAmountNum >= 0;

  /** Calculate compound escalation factor between base and target year. */
  const escalation = useMemo(() => {
    if (baseYear >= targetYear || !validRate) {
      return { factor: 1, yearlyRates: [] as { year: number; rate: number }[] };
    }

    const yearlyRates: { year: number; rate: number }[] = [];
    let factor = 1;

    for (let y = baseYear; y < targetYear; y++) {
      const rate = annualRate;

      factor *= 1 + rate / 100;
      yearlyRates.push({ year: y, rate });
    }

    return { factor, yearlyRates };
  }, [baseYear, targetYear, validRate, annualRate]);

  const escalatedAmount = useMemo(
    () => Math.round((validAmount ? baseAmountNum : 0) * escalation.factor * 100) / 100,
    [baseAmountNum, validAmount, escalation.factor],
  );

  const totalPctChange = useMemo(
    () => fmtFixed((escalation.factor - 1) * 100, 1),
    [escalation.factor],
  );

  // Whole amounts in the reader's language. The locale is read per call rather
  // than captured in a memoised formatter: switching language re-renders this
  // panel but does not remount it, so a formatter made on mount would keep the
  // separators of the language the panel opened in.
  const fmt = useCallback(
    (n: number) => n.toLocaleString(getNumberLocale(), { minimumFractionDigits: 0, maximumFractionDigits: 0 }),
    [],
  );

  const canApply = validRate && validAmount && baseYear < targetYear && Number.isFinite(escalatedAmount);
  const handleApply = useCallback(() => {
    if (canApply) onApply?.(escalatedAmount, escalation.factor);
  }, [canApply, onApply, escalatedAmount, escalation.factor]);

  return (
    <div className={clsx('rounded-xl border border-border bg-surface-primary p-5', className)}>
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-100 dark:bg-amber-900/30">
          <TrendingUp size={16} className="text-amber-600" />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('costs.escalation_calculator', { defaultValue: 'Cost Escalation Calculator' })}
          </h3>
          <p className="text-2xs text-content-tertiary">
            {t('costs.bg_escalation_desc', {
              defaultValue: 'Adjust costs using the annual rate entered for your project',
            })}
          </p>
        </div>
      </div>

      {/* Controls */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-4">
        {/* Base year */}
        <div>
          <label className="block text-2xs font-medium text-content-secondary mb-1">
            {t('costs.base_year', { defaultValue: 'Base year' })}
          </label>
          <select
            aria-label={t('costs.base_year', { defaultValue: 'Base year' })}
            value={baseYear}
            onChange={(e) => setBaseYear(Number(e.target.value))}
            className="w-full h-8 rounded-md border border-border bg-surface-primary px-2 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          >
            {YEARS.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </div>

        {/* Target year */}
        <div>
          <label className="block text-2xs font-medium text-content-secondary mb-1">
            {t('costs.target_year', { defaultValue: 'Target year' })}
          </label>
          <select
            aria-label={t('costs.target_year', { defaultValue: 'Target year' })}
            value={targetYear}
            onChange={(e) => setTargetYear(Number(e.target.value))}
            className="w-full h-8 rounded-md border border-border bg-surface-primary px-2 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          >
            {YEARS.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </div>

        {/* Amount */}
        <div>
          <label className="block text-2xs font-medium text-content-secondary mb-1">
            {t('costs.base_amount', { defaultValue: 'Base amount' })}
          </label>
          <input
            type="number"
            min={0}
            aria-label={t('costs.base_amount', { defaultValue: 'Base amount' })}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="w-full h-8 rounded-md border border-border bg-surface-primary px-2 text-xs text-content-primary tabular-nums focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          />
        </div>
      </div>

      {/* Explicit project rate: blank until the estimator supplies it. */}
      <label className="flex items-center gap-3 mb-4 p-2 rounded-lg bg-surface-secondary/50">
        <span className="text-xs text-content-secondary">
          {t('costs.manual_rate', { defaultValue: 'Manual rate (% p.a.)' })}
        </span>
        <input
          type="number"
          min={-100}
          step="0.1"
          value={manualRate}
          onChange={(e) => setManualRate(e.target.value)}
          placeholder="5.0"
          className="w-20 h-7 rounded-md border border-border bg-surface-primary px-2 text-xs text-content-primary tabular-nums focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
        />
      </label>

      {/* Year-by-year breakdown */}
      {escalation.yearlyRates.length > 0 && (
        <div className="mb-4">
          <div className="flex items-center gap-1.5 mb-2">
            <span className="text-2xs font-medium text-content-secondary uppercase tracking-wide">
              {t('costs.yearly_breakdown', { defaultValue: 'Year-by-year breakdown' })}
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {escalation.yearlyRates.map(({ year, rate }) => (
              <div
                key={year}
                className="flex items-center gap-1 rounded-md bg-surface-secondary px-2 py-1"
              >
                <span className="text-2xs text-content-tertiary">{year}</span>
                <span className="text-2xs font-medium text-amber-600">{rate >= 0 ? '+' : ''}{fmtPercent(rate)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Result */}
      <div className="rounded-lg border border-amber-200 dark:border-amber-800/50 bg-amber-50/50 dark:bg-amber-900/10 p-4">
        <div className="grid grid-cols-3 gap-4">
          <div>
            <p className="text-2xs text-content-tertiary mb-0.5">
              {t('costs.base_cost', { defaultValue: 'Base cost' })} ({baseYear})
            </p>
            <p className="text-sm font-semibold text-content-primary tabular-nums">
              {fmt(validAmount ? baseAmountNum : 0)}
            </p>
          </div>
          <div className="text-center">
            <p className="text-2xs text-content-tertiary mb-0.5">
              {t('costs.escalation_factor', { defaultValue: 'Factor' })}
            </p>
            <p className="text-sm font-semibold text-amber-600 tabular-nums">
              {fmtFixed(escalation.factor, 4)}x
              <span className="text-2xs ml-1">({escalation.factor >= 1 ? '+' : ''}{totalPctChange}%)</span>
            </p>
          </div>
          <div className="text-right">
            <p className="text-2xs text-content-tertiary mb-0.5">
              {t('costs.escalated_cost', { defaultValue: 'Escalated cost' })} ({targetYear})
            </p>
            <p className="text-sm font-bold text-content-primary tabular-nums">
              {fmt(escalatedAmount)}
            </p>
          </div>
        </div>
      </div>

      {/* Info + Apply */}
      <div className="flex items-center justify-between mt-3">
        <div className="flex items-center gap-1 text-2xs text-content-tertiary">
          <Info size={11} />
          <span>
            {t('costs.bg_escalation_disclaimer', {
              defaultValue: 'Enter the annual rate agreed for the project. No published Bulgarian index is preloaded.',
            })}
          </span>
        </div>
        {onApply && (
          <button
            onClick={handleApply}
            disabled={!canApply}
            className="flex items-center gap-1.5 rounded-md bg-oe-blue px-3 py-1.5 text-xs font-medium text-white hover:bg-oe-blue-hover disabled:opacity-50 transition-colors"
          >
            <Calculator size={13} />
            {t('costs.apply_escalation', { defaultValue: 'Apply' })}
          </button>
        )}
      </div>
    </div>
  );
}
