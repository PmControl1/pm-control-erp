import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import { hasLlmKey } from '@/features/ai-estimator/useAiReadiness';
import { AiStatusBanner } from '@/features/ai-estimator/components/AiStatusBanner';
import AIConfigBanner from '@/features/erp-chat/full-page/AIConfigBanner';
import type { AISettings } from '../api';

afterEach(cleanup);

describe('AI features with centrally managed credentials', () => {
  it('enables estimates without a personal key and honors revocation despite a saved key', () => {
    expect(hasLlmKey({ ai_ready: true, openai_api_key_set: false } as AISettings)).toBe(true);
    expect(hasLlmKey({ ai_ready: false, openai_api_key_set: true } as AISettings)).toBe(false);
    expect(hasLlmKey({ openai_api_key_set: true } as AISettings)).toBe(true);
  });

  it('does not send a team member to personal provider setup in chat or estimates', () => {
    const view = (managed: boolean, ready: boolean) => <MemoryRouter>
      <AIConfigBanner managed={managed} ready={ready} />
      <AiStatusBanner readiness={{ managed, llmReady: ready, preferredModel: 'company-model', vectorReady: true, isLoading: false }} />
    </MemoryRouter>;
    const { rerender } = render(view(true, false));
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.getByRole('status')).toHaveTextContent(/owner/i);
    rerender(view(true, true));
    expect(screen.queryByRole('status')).toBeNull();
    expect(screen.getByText('company-model')).toBeInTheDocument();
    rerender(view(false, false));
    expect(screen.getAllByRole('link')).toHaveLength(2);
  });
});
