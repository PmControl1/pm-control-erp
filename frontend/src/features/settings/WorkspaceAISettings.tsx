// Settings > AI for workspace AI: the owner sets one provider, key, model and
// system prompt for everyone; everyone else just sees that AI is ready. Below
// it, each user manages what the assistant remembers about them.
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Brain, CheckCircle2, Sparkles, Trash2 } from 'lucide-react';
import { Badge, Button, Card, CardContent, CardHeader, ConfirmDialog } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  AI_MEMORY_QUERY_KEY,
  WORKSPACE_AI_QUERY_KEY,
  providerName,
  useWorkspaceAI,
  workspaceAiApi,
  type WorkspaceAIStatus,
} from '@/features/ai/workspaceAi';

const labelClass = 'text-sm font-medium text-content-primary block mb-1.5';
const hintClass = 'mt-1.5 text-xs text-content-tertiary';
const inputClass =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary ' +
  'placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 ' +
  'focus:border-oe-blue hover:border-content-tertiary';

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** The whole workspace-AI area of the AI tab. Renders nothing while loading. */
export function WorkspaceAISection() {
  const { data } = useWorkspaceAI();
  if (!data) return null;
  return (
    <>
      {data.can_manage ? (
        <WorkspaceAIOwnerCard status={data} />
      ) : data.configured ? (
        <WorkspaceAIReadyCard status={data} />
      ) : null}
      {data.memory_enabled && <AIMemoryCard />}
    </>
  );
}

function WorkspaceAIReadyCard({ status }: { status: WorkspaceAIStatus }) {
  const { t } = useTranslation();
  return (
    <Card className="lg:col-span-2">
      <CardContent>
        <div className="flex items-start gap-3">
          <CheckCircle2 size={20} className="mt-0.5 shrink-0 text-semantic-success" />
          <div>
            <p className="text-sm font-semibold text-content-primary">
              {t('settings.workspace_ai_ready_title', { defaultValue: 'AI is ready to use' })}
            </p>
            <p className="mt-1 text-sm text-content-secondary">
              {t('settings.workspace_ai_ready_body', {
                defaultValue: 'Your workspace provides AI ({{provider}}). There is nothing to set up.',
                provider: providerName(status.provider),
              })}
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function WorkspaceAIOwnerCard({ status }: { status: WorkspaceAIStatus }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const providers = status.providers ?? ['deepseek'];

  const [provider, setProvider] = useState(status.provider ?? 'deepseek');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [memoryEnabled, setMemoryEnabled] = useState(true);
  const [confirmRemove, setConfirmRemove] = useState(false);

  // Load the saved values whenever the server copy changes.
  useEffect(() => {
    setProvider(status.provider ?? 'deepseek');
    setModel(status.configured ? status.model ?? '' : '');
    setSystemPrompt(status.system_prompt ?? '');
    setMemoryEnabled(status.memory_enabled);
    setApiKey('');
  }, [status.provider, status.model, status.system_prompt, status.memory_enabled, status.configured, status.updated_at]);

  const refresh = (next: WorkspaceAIStatus) => {
    queryClient.setQueryData(WORKSPACE_AI_QUERY_KEY, next);
    // Every page that checks "is AI ready" reads the per-user settings.
    void queryClient.invalidateQueries({ queryKey: ['ai-settings'] });
    void queryClient.invalidateQueries({ queryKey: AI_MEMORY_QUERY_KEY });
  };

  const save = useMutation({
    mutationFn: () =>
      workspaceAiApi.save({
        provider,
        model: model.trim(),
        api_key: apiKey.trim() || undefined,
        system_prompt: systemPrompt,
        memory_enabled: memoryEnabled,
      }),
    onSuccess: (next) => {
      refresh(next);
      addToast({ type: 'success', title: t('settings.workspace_ai_saved', { defaultValue: 'Workspace AI saved' }) });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('settings.workspace_ai_save_failed', { defaultValue: 'Could not save' }),
        message: errorMessage(err),
      }),
  });

  const test = useMutation({
    mutationFn: workspaceAiApi.test,
    onSuccess: (result) =>
      addToast({
        type: result.success ? 'success' : 'error',
        title: result.success
          ? t('settings.ai_test_success', { defaultValue: 'Connection successful' })
          : t('settings.ai_test_failed', { defaultValue: 'Connection failed' }),
        message: result.latency_ms != null ? `${result.message} · ${result.latency_ms} ms` : result.message,
      }),
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('settings.ai_test_failed', { defaultValue: 'Connection failed' }),
        message: errorMessage(err),
      }),
  });

  const remove = useMutation({
    mutationFn: workspaceAiApi.remove,
    onSuccess: (next) => {
      setConfirmRemove(false);
      refresh(next);
    },
    onError: (err) => {
      setConfirmRemove(false);
      addToast({ type: 'error', title: errorMessage(err) });
    },
  });

  const providerChanged = status.configured && provider !== status.provider;
  const needsKey = !status.configured || providerChanged || !status.key_set;
  const canSave = !save.isPending && (!needsKey || apiKey.trim().length > 0);
  const defaultModel = status.default_models?.[provider] ?? '';

  return (
    <Card className="lg:col-span-2">
      <CardHeader
        title={t('settings.workspace_ai_title', { defaultValue: 'Workspace AI' })}
        subtitle={t('settings.workspace_ai_subtitle', {
          defaultValue:
            'Set the AI once for everyone. Every user and customer uses this provider and key; nobody else enters a key.',
        })}
        action={
          status.configured ? (
            <Badge variant="success" size="sm" dot>
              {t('settings.workspace_ai_active', { defaultValue: 'Active for everyone' })}
            </Badge>
          ) : (
            <Badge variant="warning" size="sm" dot>
              {t('settings.workspace_ai_not_set', { defaultValue: 'Not set up' })}
            </Badge>
          )
        }
      />
      <CardContent>
        <div className="space-y-5">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="workspace-ai-provider" className={labelClass}>
                {t('settings.ai_provider', { defaultValue: 'AI Provider' })}
              </label>
              <select
                id="workspace-ai-provider"
                className={inputClass}
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
              >
                {providers.map((id) => (
                  <option key={id} value={id}>
                    {providerName(id)}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="workspace-ai-model" className={labelClass}>
                {t('settings.workspace_ai_model', { defaultValue: 'Model' })}
              </label>
              <input
                id="workspace-ai-model"
                className={`${inputClass} font-mono`}
                value={model}
                placeholder={defaultModel}
                onChange={(e) => setModel(e.target.value)}
              />
              <p className={hintClass}>
                {t('settings.workspace_ai_model_hint', {
                  defaultValue: 'Leave empty to use {{model}}.',
                  model: defaultModel,
                })}
              </p>
            </div>
          </div>

          <div>
            <label htmlFor="workspace-ai-key" className={labelClass}>
              {t('settings.ai_api_key', { defaultValue: 'API Key' })}
            </label>
            <input
              id="workspace-ai-key"
              type="password"
              autoComplete="off"
              className={`${inputClass} font-mono`}
              value={apiKey}
              placeholder={
                needsKey
                  ? t('settings.workspace_ai_key_placeholder', { defaultValue: 'Paste the API key' })
                  : t('settings.workspace_ai_key_saved', {
                      defaultValue: 'Saved ({{hint}}). Leave empty to keep it.',
                      hint: status.key_hint ?? '…',
                    })
              }
              onChange={(e) => setApiKey(e.target.value)}
            />
            <p className={hintClass}>
              {t('settings.workspace_ai_key_hint', {
                defaultValue: 'Stored encrypted on the server and never shown to anyone.',
              })}
            </p>
          </div>

          <div>
            <label htmlFor="workspace-ai-prompt" className={labelClass}>
              {t('settings.workspace_ai_prompt', { defaultValue: 'System prompt' })}
            </label>
            <textarea
              id="workspace-ai-prompt"
              rows={6}
              className={`${inputClass} h-auto py-2 leading-relaxed`}
              value={systemPrompt}
              placeholder={t('settings.workspace_ai_prompt_placeholder', {
                defaultValue:
                  'e.g. You work for a construction project management company in Bulgaria. Answer in the language the user writes in. Use euro and Bulgarian standards.',
              })}
              onChange={(e) => setSystemPrompt(e.target.value)}
            />
            <p className={hintClass}>
              {t('settings.workspace_ai_prompt_hint', {
                defaultValue: 'Added to every AI request in the app: the assistant, estimates, takeoff and the rest.',
              })}
            </p>
          </div>

          <label className="flex items-start gap-3">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4"
              checked={memoryEnabled}
              onChange={(e) => setMemoryEnabled(e.target.checked)}
            />
            <span>
              <span className="text-sm font-medium text-content-primary">
                {t('settings.workspace_ai_memory', { defaultValue: 'Assistant memory' })}
              </span>
              <span className="block text-xs text-content-tertiary">
                {t('settings.workspace_ai_memory_hint', {
                  defaultValue:
                    'The assistant remembers facts and preferences each user tells it, across conversations. Each user sees and deletes only their own.',
                })}
              </span>
            </span>
          </label>

          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!canSave}>
              {t('common.save', { defaultValue: 'Save' })}
            </Button>
            <Button
              variant="secondary"
              onClick={() => test.mutate()}
              loading={test.isPending}
              disabled={!status.configured}
            >
              {t('settings.ai_test', { defaultValue: 'Test Connection' })}
            </Button>
            {status.configured && (
              <Button variant="ghost" onClick={() => setConfirmRemove(true)} className="ml-auto">
                {t('settings.workspace_ai_turn_off', { defaultValue: 'Turn off workspace AI' })}
              </Button>
            )}
          </div>
        </div>

        <ConfirmDialog
          open={confirmRemove}
          loading={remove.isPending}
          variant="warning"
          title={t('settings.workspace_ai_turn_off_title', { defaultValue: 'Turn off workspace AI?' })}
          message={t('settings.workspace_ai_turn_off_message', {
            defaultValue: 'Users will no longer have AI unless they enter their own key. The saved key is deleted.',
          })}
          confirmLabel={t('settings.workspace_ai_turn_off', { defaultValue: 'Turn off workspace AI' })}
          onCancel={() => setConfirmRemove(false)}
          onConfirm={() => remove.mutate()}
        />
      </CardContent>
    </Card>
  );
}

function AIMemoryCard() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [draft, setDraft] = useState('');
  const { data } = useQuery({ queryKey: AI_MEMORY_QUERY_KEY, queryFn: workspaceAiApi.listMemory });
  const items = data?.items ?? [];

  const onError = (err: unknown) => addToast({ type: 'error', title: errorMessage(err) });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: AI_MEMORY_QUERY_KEY });

  const add = useMutation({
    mutationFn: () => workspaceAiApi.addMemory(draft.trim()),
    onSuccess: () => {
      setDraft('');
      void invalidate();
    },
    onError,
  });
  const del = useMutation({ mutationFn: workspaceAiApi.deleteMemory, onSuccess: invalidate, onError });
  const clear = useMutation({ mutationFn: workspaceAiApi.clearMemory, onSuccess: invalidate, onError });

  return (
    <Card className="lg:col-span-2">
      <CardHeader
        title={t('settings.ai_memory_title', { defaultValue: 'What the assistant remembers about you' })}
        subtitle={t('settings.ai_memory_subtitle', {
          defaultValue: 'Ask the assistant to remember something, or add it here. Only you can see this list.',
        })}
        action={
          items.length > 0 ? (
            <Button variant="ghost" size="sm" onClick={() => clear.mutate()} loading={clear.isPending}>
              {t('settings.ai_memory_clear', { defaultValue: 'Forget everything' })}
            </Button>
          ) : undefined
        }
      />
      <CardContent>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (draft.trim()) add.mutate();
          }}
        >
          <input
            className={inputClass}
            value={draft}
            maxLength={1000}
            placeholder={t('settings.ai_memory_placeholder', {
              defaultValue: 'e.g. I am a site engineer; keep answers short.',
            })}
            onChange={(e) => setDraft(e.target.value)}
          />
          <Button type="submit" variant="secondary" loading={add.isPending} disabled={!draft.trim()}>
            {t('settings.ai_memory_add', { defaultValue: 'Remember' })}
          </Button>
        </form>

        {items.length === 0 ? (
          <p className="mt-4 flex items-center gap-2 text-sm text-content-tertiary">
            <Brain size={16} />
            {t('settings.ai_memory_empty', { defaultValue: 'Nothing saved yet.' })}
          </p>
        ) : (
          <ul className="mt-4 divide-y divide-border-light">
            {items.map((item) => (
              <li key={item.id} className="flex items-start gap-3 py-2.5">
                {item.source === 'assistant' ? (
                  <Sparkles size={14} className="mt-1 shrink-0 text-oe-blue" />
                ) : (
                  <Brain size={14} className="mt-1 shrink-0 text-content-tertiary" />
                )}
                <span className="flex-1 text-sm text-content-primary">{item.content}</span>
                <button
                  type="button"
                  className="rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-semantic-error"
                  aria-label={t('settings.ai_memory_delete', { defaultValue: 'Forget this' })}
                  onClick={() => del.mutate(item.id)}
                >
                  <Trash2 size={14} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
