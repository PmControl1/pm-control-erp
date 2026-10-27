// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Modified 2026 for PM Project Management: the upstream logo and wordmark are
// replaced by the brand configured in shared/brand.ts.
import clsx from 'clsx';
import { BRAND_LOGO_URL, BRAND_NAME } from '@/shared/brand';

interface LogoProps {
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
  /** Kept for API compatibility with upstream callers; the brand logo is static. */
  animate?: boolean;
  className?: string;
}

/* Icon sizes — compact so the text dominates */
const sizeMap = {
  xs: 'h-5 w-5',
  sm: 'h-6 w-6',
  md: 'h-7 w-7',
  lg: 'h-10 w-10',
  xl: 'h-14 w-14',
};

/** Brand mark, loaded from BRAND_LOGO_URL. */
export function Logo({ size = 'md', className }: LogoProps) {
  return (
    <div className={clsx(sizeMap[size], 'relative shrink-0', className)}>
      <img
        src={BRAND_LOGO_URL}
        alt={BRAND_NAME}
        className="w-full h-full object-contain"
        draggable={false}
      />
    </div>
  );
}

/* ── LogoWithText ──────────────────────────────────────────────────────── */

interface LogoWithTextProps extends LogoProps {
  /** Kept for API compatibility with upstream callers. */
  showVersion?: boolean;
}

/* Text sizes — larger than icon to make the name prominent */
const textSizeMap = {
  xs: 'text-[15px] leading-none',
  sm: 'text-[16px] leading-none',
  md: 'text-[17px] leading-none',
  lg: 'text-xl leading-none',
  xl: 'text-2xl leading-none',
};

const gapSizeMap = {
  xs: 'gap-1.5',
  sm: 'gap-2',
  md: 'gap-2',
  lg: 'gap-2.5',
  xl: 'gap-3',
};

/** Logo + product name. */
export function LogoWithText({ size = 'md', animate, className }: LogoWithTextProps) {
  return (
    <div className={clsx('flex items-center', gapSizeMap[size], className)}>
      <Logo size={size} animate={animate} />
      <span
        className={clsx(
          textSizeMap[size],
          'font-semibold text-content-primary whitespace-nowrap tracking-tight',
        )}
        style={{ fontFamily: "'Plus Jakarta Sans', system-ui, sans-serif", letterSpacing: '-0.02em' }}
      >
        {BRAND_NAME}
      </span>
    </div>
  );
}
