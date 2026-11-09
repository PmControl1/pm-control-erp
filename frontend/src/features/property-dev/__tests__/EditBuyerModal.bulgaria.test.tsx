import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { EditBuyerModal } from '../EditBuyerModal';
import { type Buyer, updateBuyer } from '../api';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return { ...actual, listJurisdictions: vi.fn().mockResolvedValue([]), updateBuyer: vi.fn() };
});

afterEach(() => { cleanup(); vi.clearAllMocks(); });

const buyer = {
  id: 'buyer', development_id: 'development', full_name: 'Legacy buyer', email: 'buyer@test.io',
  language: 'de', status: 'lead', currency: 'EUR', contract_value: '0',
} as Buyer;

function renderBuyer() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>
    <EditBuyerModal open buyer={buyer} plots={[]} developmentId="development" onClose={vi.fn()} />
  </QueryClientProvider>);
}

describe('Bulgarian buyer language options', () => {
  it('displays a legacy language and preserves it when another field is edited', async () => {
    vi.mocked(updateBuyer).mockResolvedValue({ ...buyer, full_name: 'Updated buyer' });
    renderBuyer();
    expect(screen.getByTestId('edit-buyer-language')).toHaveValue('de');
    expect(screen.getByRole('option', { name: /Български/ })).toHaveValue('bg');
    expect(screen.queryByRole('option', { name: /Français/ })).toBeNull();
    fireEvent.change(screen.getByTestId('edit-buyer-full-name'), { target: { value: 'Updated buyer' } });
    fireEvent.click(screen.getByRole('button', { name: /Save/ }));
    await waitFor(() => expect(updateBuyer).toHaveBeenCalledWith('buyer', { full_name: 'Updated buyer' }));
  });
});
