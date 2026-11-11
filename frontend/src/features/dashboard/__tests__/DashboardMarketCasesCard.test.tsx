// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Country-specific examples no longer belong on the Bulgarian product's
// dashboard. Existing saved layouts must lose the obsolete widget too.

import { describe, expect, it } from 'vitest';

import { PLAYBOOKS } from '@/features/cases/playbooks';
import { reconcileOrder } from '@/stores/useDashboardLayoutStore';
import { DASHBOARD_WIDGET_BY_ID, DASHBOARD_WIDGET_IDS, DASHBOARD_WIDGETS } from '../widgetRegistry';

describe('country-neutral dashboard cases', () => {
  it('offers the neutral learning gallery without a country-specific widget', () => {
    expect(DASHBOARD_WIDGET_BY_ID.cases_learn).toBeDefined();
    expect(DASHBOARD_WIDGET_BY_ID.cases_market).toBeUndefined();
    expect(DASHBOARD_WIDGETS.some((widget) => widget.id === 'cases_market')).toBe(false);
    expect(PLAYBOOKS.length).toBeGreaterThan(0);
    expect(PLAYBOOKS.every((playbook) => !playbook.region)).toBe(true);
  });

  it('drops the removed market widget from an existing saved dashboard layout', () => {
    const saved = ['cases_market', 'cases_learn', 'regional_pack', 'today'];
    const order = reconcileOrder(saved, DASHBOARD_WIDGET_IDS);

    expect(order).not.toContain('cases_market');
    expect(order).toContain('cases_learn');
    expect(new Set(order)).toEqual(new Set(DASHBOARD_WIDGET_IDS));
    expect(order.indexOf('cases_learn')).toBeLessThan(order.indexOf('regional_pack'));
  });
});
