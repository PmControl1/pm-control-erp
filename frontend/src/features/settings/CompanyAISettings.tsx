import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import type { CompanyAIProvider, ManagedAI } from '@/features/ai/api';
import { companyAiStatusText } from '@/features/ai/companyAiStatus';
import { apiGet, apiPost, apiPut } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { Button, Card, CardContent, CardHeader, Input, Skeleton } from '@/shared/ui';

interface CompanyConfig {
  provider: CompanyAIProvider;
  model: string;
  key_set: boolean;
}

interface AITeam {
  id: string;
  name: string;
  project_name: string;
  active: boolean;
  enabled: boolean;
  eligible_members: number;
  approved_members: number;
  pending_members: number;
}

const configPath = '/v1/ai/company/settings/';
const teamsPath = '/v1/ai/internal-pilot/teams/';

export function CompanyAISettings({ managed, userId, defaults }: {
  managed: ManagedAI;
  userId: string | null;
  defaults: Record<string, string>;
}) {
  const { t } = useTranslation();
  return (
    <Card className="lg:col-span-2">
      <CardHeader title={t('company_ai.title', { defaultValue: 'Company AI' })} />
      <CardContent>
        {managed.is_owner ? (
          <OwnerSettings userId={userId} defaults={defaults} />
        ) : (
          <p role="status">
            {companyAiStatusText(t, managed.has_access && managed.configured)}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function OwnerSettings({ userId, defaults }: { userId: string | null; defaults: Record<string, string> }) {
  const { t } = useTranslation();
  const cache = useQueryClient();
  const addToast = useToastStore((state) => state.addToast);
  const configKey = ['company-ai-settings', userId];
  const teamsKey = ['company-ai-teams', userId];
  const config = useQuery({ queryKey: configKey, queryFn: () => apiGet<CompanyConfig>(configPath), retry: false });
  const teams = useQuery({ queryKey: teamsKey, queryFn: () => apiGet<{ teams: AITeam[] }>(teamsPath), retry: false });
  const grant = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => apiPut<AITeam>(teamsPath + encodeURIComponent(id), { enabled }),
    onSuccess: (updated) => {
      cache.setQueryData<{ teams: AITeam[] }>(teamsKey, (current) =>
        current && { teams: current.teams.map((team) => team.id === updated.id ? updated : team) });
      void cache.invalidateQueries({ queryKey: teamsKey });
      void cache.invalidateQueries({ queryKey: ['ai-settings'] });
    },
  });

  return (
    <div className="space-y-6">
      {config.isError ? (
        <div role="alert">
          {t('company_ai.load_error', { defaultValue: 'Could not load the AI settings.' })}
          <Button variant="secondary" onClick={() => void config.refetch()}>{t('common.retry', { defaultValue: 'Retry' })}</Button>
        </div>
      ) : config.data ? (
        <ProviderForm key={JSON.stringify(config.data)} saved={config.data} defaults={defaults} onSaved={(updated) => {
          cache.setQueryData(configKey, updated);
          addToast({ type: 'success', title: t('company_ai.saved', { defaultValue: 'Company AI settings saved.' }) });
          void cache.invalidateQueries({ queryKey: ['ai-settings'] });
        }} />
      ) : <Skeleton height={100} />}
      <section aria-labelledby="company-ai-teams" className="border-t border-border-light pt-4">
        <h4 id="company-ai-teams" className="font-semibold">{t('company_ai.teams', { defaultValue: 'Team access' })}</h4>
        <p className="mt-1 text-sm text-content-secondary">
          {t('company_ai.grants_hint', { defaultValue: 'Approval covers current eligible members. Approve new members when they join. Removing someone from a team ends the access granted by that team.' })}
        </p>
        <Link to="/teams" className="text-sm text-oe-blue hover:underline">
          {t('company_ai.review_members', { defaultValue: 'Review project teams and their members' })}
        </Link>
        {teams.isError ? (
          <div role="alert">
            {t('company_ai.teams_error', { defaultValue: 'Could not load project teams.' })}
            <Button variant="secondary" onClick={() => void teams.refetch()}>{t('common.retry', { defaultValue: 'Retry' })}</Button>
          </div>
        ) : !teams.data ? <Skeleton height={48} /> : teams.data.teams.length === 0 ? (
          <p className="mt-3">{t('company_ai.no_teams', { defaultValue: 'Create a project team to grant access.' })}</p>
        ) : (
          <ul className="mt-3 divide-y divide-border-light">
            {teams.data.teams.map((team) => (
              <li key={team.id} className="flex flex-wrap items-center justify-between gap-3 py-2">
                <div>
                  <span className="font-medium">{team.name}</span> · {team.project_name}
                  <p className="text-xs text-content-secondary">
                    {t('company_ai.approved_count', { defaultValue: '{{approved}} of {{eligible}} eligible members approved', approved: team.approved_members, eligible: team.eligible_members })}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {team.active && team.enabled && team.pending_members > 0 && (
                    <Button variant="secondary" disabled={grant.isPending} onClick={() => grant.mutate({ id: team.id, enabled: true })}>
                      {t('company_ai.approve_new', { defaultValue: 'Approve new members' })}
                    </Button>
                  )}
                  <Button variant={team.enabled ? 'secondary' : 'primary'} disabled={grant.isPending || (!team.active && !team.enabled)}
                    onClick={() => grant.mutate({ id: team.id, enabled: !team.enabled })}>
                    {team.enabled ? t('company_ai.revoke', { defaultValue: 'Revoke access' }) : t('company_ai.grant', { defaultValue: 'Grant access' })}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
        {grant.isError && <p role="alert">{t('company_ai.grant_error', { defaultValue: 'Could not update team access. Refresh and try again.' })}</p>}
      </section>
    </div>
  );
}

function ProviderForm({ saved, defaults, onSaved }: {
  saved: CompanyConfig;
  defaults: Record<string, string>;
  onSaved: (updated: CompanyConfig) => void;
}) {
  const { t } = useTranslation();
  const [provider, setProvider] = useState(saved.provider);
  const [model, setModel] = useState(saved.model);
  const [secret, setSecret] = useState('');
  const needsKey = !saved.key_set || provider !== saved.provider;
  const dirty = provider !== saved.provider || model.trim() !== saved.model || !!secret.trim();
  const save = useMutation({
    // Keep the secret out of mutation variables and the query cache.
    mutationFn: () => apiPut<CompanyConfig>(configPath, { provider, model: model.trim(), ...(secret.trim() && { api_key: secret.trim() }) }),
    onSuccess: (updated) => { setSecret(''); onSaved(updated); },
  });
  const test = useMutation({
    mutationFn: () => apiPost<{ success: boolean }>(configPath + 'test/'),
  });
  const busy = save.isPending || test.isPending;
  const validModel = /^[a-z\d][a-z\d._:/-]{0,99}$/i.test(model.trim());
  const canSave = dirty && validModel && (!needsKey || !!secret.trim());

  function submit(event: FormEvent) {
    event.preventDefault();
    if (canSave && !busy) save.mutate();
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <label className="block text-sm font-medium">
        {t('company_ai.provider', { defaultValue: 'Company provider' })}
        <select value={provider} disabled={busy} className="mt-1 block rounded border border-border bg-surface-primary p-2"
          onChange={(event) => {
            const next = event.target.value as CompanyAIProvider;
            setProvider(next);
            setModel(next === saved.provider ? saved.model : defaults?.[next] ?? '');
            setSecret('');
            test.reset();
            save.reset();
          }}>
          <option value="deepseek">DeepSeek</option>
          <option value="openai">OpenAI</option>
        </select>
      </label>
      <Input id="company-ai-model" required maxLength={100} label={t('company_ai.model', { defaultValue: 'Model ID' })}
        error={model && !validModel ? t('company_ai.model_error', { defaultValue: 'Enter a valid provider model ID.' }) : undefined}
        disabled={busy} value={model} onChange={(event) => { setModel(event.target.value); save.reset(); test.reset(); }} />
      <Input id="company-ai-key" type="password" autoComplete="new-password" value={secret} required={needsKey}
        disabled={busy} label={t('company_ai.key', { defaultValue: 'Company API key' })}
        hint={needsKey ? t('company_ai.key_required', { defaultValue: 'Enter a key for this provider.' }) : t('company_ai.key_saved', { defaultValue: 'A key is saved. Leave this blank to keep it or enter a replacement.' })}
        onChange={(event) => { setSecret(event.target.value); save.reset(); test.reset(); }} />
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={!canSave || busy}>{t('common.save', { defaultValue: 'Save' })}</Button>
        <Button type="button" variant="secondary" disabled={!saved.key_set || dirty || busy}
          onClick={() => test.mutate()}>{t('company_ai.test', { defaultValue: 'Test saved connection' })}</Button>
      </div>
      {save.isError && <p role="alert">{t('company_ai.save_error', { defaultValue: 'Could not save the company configuration. Check the model ID and key.' })}</p>}
      {test.isSuccess && test.data.success && <p role="status">{t('company_ai.connected', { defaultValue: 'The saved connection works.' })}</p>}
      {(test.isError || (test.isSuccess && !test.data.success)) && (
        <p role="alert">{t('company_ai.test_error', { defaultValue: 'Connection failed. Check the saved provider, model and key.' })}</p>
      )}
    </form>
  );
}
