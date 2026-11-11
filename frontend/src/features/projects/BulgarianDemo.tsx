import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, Building2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { apiPost } from '@/shared/lib/api';
import { Button } from '@/shared/ui/Button';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import type { Project } from './api';
import { invalidateProjectLists } from './invalidateProjectLists';

export const BULGARIAN_DEMO_ID = 'pm-bg-plovdiv-v1';

interface InstallResult {
  project_id: string;
  project_name: string;
  already_installed: boolean;
}

export function BulgarianDemoCard({ role, projects }: { role?: string; projects: Project[] }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);
  const existing = projects.find((p) => p.metadata?.demo_id === BULGARIAN_DEMO_ID && p.status !== 'archived');
  const openProject = (id: string, name: string) => {
    setActiveProject(id, name);
    navigate(`/projects/${id}`);
  };
  const install = useMutation({
    mutationFn: () => apiPost<InstallResult>('/v1/projects/demo/bulgaria', {}),
    onSuccess: (result) => {
      invalidateProjectLists(queryClient);
      queryClient.invalidateQueries({ queryKey: ['projects-dashboard-cards'] });
      addToast({ type: 'success', title: t('bg_demo.success') });
      openProject(result.project_id, result.project_name);
    },
    onError: (error: Error) => addToast({ type: 'error', title: t('bg_demo.failed'), message: error.message }),
  });

  if (role !== 'admin' && !existing) return null;

  return (
    <section className="flex flex-col gap-4 rounded-xl border border-oe-blue/20 bg-oe-blue-subtle p-4 sm:flex-row sm:items-center sm:justify-between" aria-labelledby="bg-demo-title">
      <div className="min-w-0">
        <h2 id="bg-demo-title" className="flex items-center gap-2 text-sm font-semibold text-content-primary">
          <Building2 size={18} aria-hidden="true" />{t('bg_demo.title')}
        </h2>
        <p className="mt-1 max-w-3xl text-sm text-content-secondary">{t('bg_demo.description')}</p>
      </div>
      <Button
        variant="secondary"
        loading={install.isPending}
        icon={<ArrowRight size={16} />}
        onClick={() => existing ? openProject(existing.id, existing.name) : install.mutate()}
        data-testid="bulgarian-demo-open"
      >
        {t(existing ? 'bg_demo.open' : 'bg_demo.create')}
      </Button>
    </section>
  );
}

export function BulgarianDemoGuide({ project }: { project: Project }) {
  const { t } = useTranslation();
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);
  if (project.metadata?.demo_id !== BULGARIAN_DEMO_ID) return null;
  const steps = [
    ['boq', `/projects/${project.id}/boq`],
    ['schedule', '/schedule'],
    ['tender', '/tendering'],
    ['finance', `/projects/${project.id}/finance`],
    ['quality', '/punchlist'],
    ['rfi', `/projects/${project.id}/rfi`],
    ['risks', '/risks'],
    ['tasks', `/projects/${project.id}/tasks`],
    ['documents', `/projects/${project.id}/files`],
  ] as const;

  return (
    <section className="rounded-xl border border-oe-blue/20 bg-oe-blue-subtle p-4" aria-labelledby="bg-demo-guide-title">
      <h2 id="bg-demo-guide-title" className="text-sm font-semibold text-content-primary">{t('bg_demo.guide_title')}</h2>
      <p className="mt-1 text-sm text-content-secondary">{t('bg_demo.guide_description')}</p>
      <ol className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {steps.map(([key, to], index) => (
          <li key={key}>
            <Link to={to} onClick={() => setActiveProject(project.id, project.name)} className="block h-full rounded-lg border border-border bg-surface-primary p-3 hover:border-oe-blue focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue">
              <span className="text-sm font-semibold text-content-primary">{index + 1}. {t(`bg_demo.${key}`)}</span>
              <span className="mt-1 block text-xs text-content-secondary">{t(`bg_demo.${key}_hint`)}</span>
            </Link>
          </li>
        ))}
      </ol>
      <p className="mt-3 text-xs text-content-secondary">{t('bg_demo.share')}</p>
    </section>
  );
}
