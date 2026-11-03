import type { TFunction } from 'i18next';
import { useQuery } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/useAuthStore';
import { aiApi } from './api';

export function useWorkspaceAiSettings(enabled = true) {
  const userId = useAuthStore((state) => state.userId);
  return useQuery({
    queryKey: ['ai-settings', userId],
    queryFn: () => aiApi.getSettings(),
    enabled,
    staleTime: 60_000,
    retry: false,
  });
}

export function companyAiStatusText(t: TFunction, ready: boolean) {
  return ready
    ? t('company_ai.member_ready', { defaultValue: 'Your team can use the company’s AI in the existing tools.' })
    : t('company_ai.member_unavailable', { defaultValue: 'Company AI is unavailable for your account. Contact your platform owner.' });
}
