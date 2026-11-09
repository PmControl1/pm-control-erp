import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { EscalationCalculator } from './EscalationCalculator';

const annualRateInput = () => screen.getByRole('spinbutton', { name: /Manual rate/ });
const applyButton = () => screen.getByRole('button', { name: 'Apply' });

function enterRate(rate: string) {
  fireEvent.change(annualRateInput(), { target: { value: rate } });
}

describe('EscalationCalculator', () => {
  it('opens with no assumed country index or annual rate', () => {
    const apply = vi.fn<(amount: number, factor: number) => void>();
    render(<EscalationCalculator onApply={apply} />);
    expect(screen.getByText(/Cost Escalation Calculator/)).toBeInTheDocument();
    expect(screen.queryByText('Germany')).not.toBeInTheDocument();
    expect(screen.getAllByRole('combobox')).toHaveLength(2);
    expect(annualRateInput()).toHaveValue(null);
    expect(applyButton()).toBeDisabled();
    fireEvent.click(applyButton());
    expect(apply).not.toHaveBeenCalled();
  });

  it('compounds the entered annual rate and applies the calculated amount', () => {
    const apply = vi.fn<(amount: number, factor: number) => void>();
    render(<EscalationCalculator baseAmount={50000} onApply={apply} />);
    enterRate('10');
    fireEvent.click(applyButton());
    expect(apply).toHaveBeenCalledOnce();
    const [amount, factor] = apply.mock.calls[0]!;
    expect(factor).toBeCloseTo(1.331, 10);
    expect(amount).toBe(66550);
    expect(screen.getAllByText('+10.0%')).toHaveLength(3);
  });

  it('accepts an explicitly entered zero rate without inventing escalation', () => {
    const apply = vi.fn<(amount: number, factor: number) => void>();
    render(<EscalationCalculator baseAmount={1234.56} onApply={apply} />);
    enterRate('0');
    expect(applyButton()).toBeEnabled();
    fireEvent.click(applyButton());
    expect(apply).toHaveBeenCalledWith(1234.56, 1);
  });

  it('supports a project-agreed negative rate', () => {
    const apply = vi.fn<(amount: number, factor: number) => void>();
    render(<EscalationCalculator baseAmount={1000} onApply={apply} />);
    enterRate('-10');
    fireEvent.click(applyButton());
    expect(apply).toHaveBeenCalledOnce();
    const [amount, factor] = apply.mock.calls[0]!;
    expect(amount).toBe(729);
    expect(factor).toBeCloseTo(0.729, 10);
    expect(screen.queryByText(/\+-/)).not.toBeInTheDocument();
  });

  it('requires a new rate after the input is cleared', () => {
    render(<EscalationCalculator onApply={vi.fn()} />);
    enterRate('5');
    expect(applyButton()).toBeEnabled();
    enterRate('');
    expect(applyButton()).toBeDisabled();
  });

  it('refuses rates below minus 100 percent', () => {
    render(<EscalationCalculator onApply={vi.fn()} />);
    enterRate('-101');
    expect(applyButton()).toBeDisabled();
  });

  it('does not apply escalation when the years are equal or reversed', () => {
    render(<EscalationCalculator onApply={vi.fn()} />);
    enterRate('5');
    fireEvent.change(screen.getByRole('combobox', { name: 'Base year' }), { target: { value: '2026' } });
    expect(applyButton()).toBeDisabled();
    expect(screen.getByText(/1\.0000x/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox', { name: 'Base year' }), { target: { value: '2027' } });
    expect(applyButton()).toBeDisabled();
  });

  it('preserves a zero base amount and rejects negative or blank amounts', () => {
    const apply = vi.fn<(amount: number, factor: number) => void>();
    render(<EscalationCalculator baseAmount={0} onApply={apply} />);
    const amountInput = screen.getByRole('spinbutton', { name: 'Base amount' });
    expect(amountInput).toHaveValue(0);
    enterRate('5');
    fireEvent.click(applyButton());
    expect(apply).toHaveBeenCalledOnce();
    const [amount] = apply.mock.calls[0]!;
    expect(amount).toBe(0);
    fireEvent.change(amountInput, { target: { value: '-100' } });
    expect(applyButton()).toBeDisabled();
    fireEvent.change(amountInput, { target: { value: '' } });
    expect(applyButton()).toBeDisabled();
  });

  it('explains that a Bulgarian index has not been preloaded', () => {
    render(<EscalationCalculator />);
    expect(screen.getByText(/No published Bulgarian index is preloaded/)).toBeInTheDocument();
  });
});
