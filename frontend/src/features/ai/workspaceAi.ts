// Workspace AI: one provider, key, model and system prompt set by the platform
// owner and used by every signed-in user, plus the assistant's per-user memory.
import { useQuery } from '@tanstack/react-query';
import { apiDelete, apiGet, apiPost, apiPut } from '@/shared/lib/api';

export interface WorkspaceAIStatus {
  configured: boolean;
  provider: string | null;
  model: string | null;
  memory_enabled: boolean;
  can_manage: boolean;
  // Present only for the owner.
  providers?: string[];
  default_models?: Record<string, string>;
  system_prompt?: string;
  key_set?: boolean;
  key_hint?: string | null;
  updated_at?: string | null;
}

export interface WorkspaceAIUpdate {
  provider: string;
  model: string;
  /** Leave empty to keep the saved key (same provider only). */
  api_key?: string;
  system_prompt: string;
  memory_enabled: boolean;
}

export interface WorkspaceAITestResult {
  success: boolean;
  message: string;
  latency_ms: number | null;
  model?: string;
}

export interface AIMemoryItem {
  id: string;
  content: string;
  source: 'user' | 'assistant' | string;
  created_at: string | null;
}

export const WORKSPACE_AI_QUERY_KEY = ['ai-workspace'] as const;
export const AI_MEMORY_QUERY_KEY = ['ai-memory'] as const;

export const workspaceAiApi = {
  get: () => apiGet<WorkspaceAIStatus>('/v1/ai/workspace/'),
  save: (data: WorkspaceAIUpdate) => apiPut<WorkspaceAIStatus, WorkspaceAIUpdate>('/v1/ai/workspace/', data),
  remove: () => apiDelete<WorkspaceAIStatus>('/v1/ai/workspace/'),
  test: () => apiPost<WorkspaceAITestResult>('/v1/ai/workspace/test/'),
  listMemory: () => apiGet<{ enabled: boolean; items: AIMemoryItem[] }>('/v1/ai/memory/'),
  addMemory: (content: string) => apiPost<AIMemoryItem, { content: string }>('/v1/ai/memory/', { content }),
  deleteMemory: (id: string) => apiDelete<{ deleted: number }>(`/v1/ai/memory/${id}`),
  clearMemory: () => apiDelete<{ deleted: number }>('/v1/ai/memory/'),
};

export function useWorkspaceAI() {
  return useQuery({
    queryKey: WORKSPACE_AI_QUERY_KEY,
    queryFn: workspaceAiApi.get,
    staleTime: 30_000,
  });
}

/** Display names for the providers the owner can choose. */
export const WORKSPACE_PROVIDER_NAMES: Record<string, string> = {
  deepseek: 'DeepSeek',
  anthropic: 'Anthropic Claude',
  openai: 'OpenAI',
  gemini: 'Google Gemini',
  openrouter: 'OpenRouter',
  mistral: 'Mistral AI',
  groq: 'Groq',
  xai: 'xAI Grok',
  kimi: 'Kimi (Moonshot AI)',
  together: 'Together AI',
  fireworks: 'Fireworks AI',
};

export function providerName(id: string | null | undefined): string {
  if (!id) return '';
  return WORKSPACE_PROVIDER_NAMES[id] ?? id;
}
