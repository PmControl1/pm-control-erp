import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MarkupPanel } from '../MarkupPanel';
import { BatchActionBar } from '../BatchActionBar';
import { boqApi, type Markup } from '../api';

const importedMarkup: Markup = {
  id: 'imported-tax', boq_id: 'bill', name: 'Imported tax', markup_type: 'percentage',
  category: 'tax', percentage: 19, fixed_amount: 0, apply_to: 'direct_cost',
  sort_order: 0, is_active: true, metadata: {}, created_at: '', updated_at: '',
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function renderMarkups(markups: Markup[] = []) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MarkupPanel boqId="bill" markups={markups} directCost={100} currencySymbol="€"
        currencyCode="EUR" locale="bg" fmt={new Intl.NumberFormat('bg-BG')} />
    </QueryClientProvider>,
  );
}

function renderBatch(classificationStandard?: string) {
  const apply = vi.fn();
  render(<BatchActionBar selectedIds={['position']} onBatchDelete={vi.fn()}
    onBatchChangeUnit={vi.fn()} onClearSelection={vi.fn()}
    classificationStandard={classificationStandard} onBatchSetClassification={apply} />);
  return apply;
}

describe('Bulgarian BOQ controls', () => {
  it('applies the Bulgarian template directly without a foreign market picker', async () => {
    const apply = vi.spyOn(boqApi, 'applyDefaults').mockResolvedValue([]);
    renderMarkups();
    expect(screen.queryByRole('combobox')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Apply Bulgarian template' }));
    await waitFor(() => expect(apply).toHaveBeenCalledWith('bill', 'BG'));
  });

  it('keeps imported markups until replacement is explicitly confirmed', () => {
    const apply = vi.spyOn(boqApi, 'applyDefaults').mockResolvedValue([]);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderMarkups([importedMarkup]);
    expect(screen.getByText('Imported tax')).toBeInTheDocument();
    expect(apply).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Apply Bulgarian template' }));
    expect(confirm).toHaveBeenCalled();
    expect(apply).not.toHaveBeenCalled();
    expect(screen.getByText('Imported tax')).toBeInTheDocument();
  });

  it.each([undefined, 'none', 'bg_kss'])('does not offer a foreign classification for %s bills', (standard) => {
    renderBatch(standard);
    expect(screen.queryByRole('button', { name: 'Set classification' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Change unit' })).toBeInTheDocument();
  });

  it('can edit a legacy declared standard without switching it to another country standard', () => {
    const apply = renderBatch('nrm');
    fireEvent.click(screen.getByRole('button', { name: 'Set classification' }));
    expect(screen.getByText('NRM')).toBeInTheDocument();
    expect(screen.queryByRole('combobox')).toBeNull();
    expect(screen.queryByText('DIN 276')).toBeNull();
    fireEvent.change(screen.getByRole('textbox', { name: 'Code' }), { target: { value: '2.6.1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(apply).toHaveBeenCalledWith(['position'], 'nrm', '2.6.1');
  });
});
