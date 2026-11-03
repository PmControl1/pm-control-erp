import { describe, expect, it } from 'vitest';
import type { AISettings } from '@/features/ai/api';
import { hasLlmKey } from './useAiReadiness';

describe('AI readiness without provider disclosures', () => {
  it('accepts workspace availability without exposing a configured provider key', () => {
    expect(hasLlmKey({
      workspace_managed: true, ai_ready: true, preferred_model: 'workspace',
      openai_api_key_set: false, deepseek_api_key_set: false,
    } as AISettings)).toBe(true);
  });

  it('honours an unavailable workspace even if a stale personal key flag remains', () => {
    expect(hasLlmKey({ workspace_managed: true, ai_ready: false, openai_api_key_set: true } as AISettings)).toBe(false);
  });

  it('keeps compatibility with older personal-key and local-runtime responses', () => {
    expect(hasLlmKey({ openai_api_key_set: true } as AISettings)).toBe(true);
    expect(hasLlmKey({ ollama_base_url: 'http://localhost:11434' } as AISettings)).toBe(true);
    expect(hasLlmKey(undefined)).toBe(false);
  });
});
