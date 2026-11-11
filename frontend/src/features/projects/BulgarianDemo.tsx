import { useEffect, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, Building2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { apiPost } from '@/shared/lib/api';
import { Button } from '@/shared/ui/Button';
import { WideModal } from '@/shared/ui/WideModal';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import type { Project } from './api';
import { invalidateProjectLists } from './invalidateProjectLists';

export const BULGARIAN_DEMO_ID = 'pm-bg-plovdiv-v1';
export const BULGARIAN_DEMOS = [
  { templateId: 'residential', demoId: BULGARIAN_DEMO_ID, labelKey: 'bg_demo.residential', descriptionKey: 'bg_demo.residential_description' },
  { templateId: 'office-renovation', demoId: 'pm-bg-office-v1', labelKey: 'bg_demo.office', descriptionKey: 'bg_demo.office_description' },
  { templateId: 'logistics-warehouse', demoId: 'pm-bg-warehouse-v1', labelKey: 'bg_demo.warehouse', descriptionKey: 'bg_demo.warehouse_description' },
] as const;
type DemoTemplateId = typeof BULGARIAN_DEMOS[number]['templateId'];

interface InstallResult {
  project_id: string;
  project_name: string;
  already_installed: boolean;
}

export function BulgarianDemoLauncher({ onOpened, className, compact = false }: { onOpened?: () => void; className?: string; compact?: boolean }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [chooserOpen, setChooserOpen] = useState(false);
  const launcherRef = useRef<HTMLButtonElement>(null);
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);
  const openProject = (id: string, name: string) => {
    useProjectContextStore.getState().setActiveBOQ(null);
    setActiveProject(id, name);
    navigate(`/projects/${id}`);
  };
  const install = useMutation({
    mutationFn: (templateId: DemoTemplateId) => apiPost<InstallResult>('/v1/projects/demo/bulgaria', { template_id: templateId }),
    onSuccess: async (result) => {
      invalidateProjectLists(queryClient);
      // Join the active list refresh before switching: the header otherwise
      // can discard the newly created id against its old cached list.
      await queryClient.refetchQueries({ queryKey: ['projects'], type: 'active' }, { cancelRefetch: false });
      queryClient.invalidateQueries({ queryKey: ['projects-dashboard-cards'] });
      addToast({ type: 'success', title: t('bg_demo.success') });
      setChooserOpen(false);
      openProject(result.project_id, result.project_name);
      onOpened?.();
    },
    onError: (error: Error) => addToast({ type: 'error', title: t('bg_demo.failed'), message: error.message }),
  });

  useEffect(() => {
    if (!chooserOpen || !install.isPending) return;
    // Disabling the chosen button can move browser focus to the page body.
    // Capture before the underlying picker's document listener so Escape
    // cannot unmount a pending installation, regardless of its event target.
    const keepPendingChooserOpen = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      event.stopPropagation();
    };
    window.addEventListener('keydown', keepPendingChooserOpen, true);
    return () => window.removeEventListener('keydown', keepPendingChooserOpen, true);
  }, [chooserOpen, install.isPending]);

  return (
    <span
      className={className}
      onMouseDown={(event) => { if (chooserOpen) event.stopPropagation(); }}
    >
    <Button
      ref={launcherRef}
      variant="secondary"
      className={className}
      loading={install.isPending}
      icon={<ArrowRight size={16} />}
      onClick={() => setChooserOpen(true)}
      data-testid="bulgarian-demo-open"
      aria-label={t('bg_demo.explore')}
      title={t('bg_demo.explore')}
    >
      {t(compact ? 'bg_demo.short' : 'bg_demo.explore')}
    </Button>
    <WideModal
      open={chooserOpen}
      onClose={() => { setChooserOpen(false); launcherRef.current?.focus(); }}
      title={t('bg_demo.choose_title')}
      subtitle={t('bg_demo.choose_description')}
      size="md"
      busy={install.isPending}
      testId="bulgarian-demo-chooser"
    >
      <div className="space-y-3">
        {BULGARIAN_DEMOS.map((template) => (
          <div key={template.templateId} className="rounded-lg border border-border p-4">
            <Button
              variant="secondary"
              className="w-full justify-start !h-auto min-h-10 !whitespace-normal text-left py-2"
              disabled={install.isPending}
              loading={install.isPending && install.variables === template.templateId}
              onClick={() => install.mutate(template.templateId)}
              data-testid={`bulgarian-demo-${template.templateId}`}
              aria-label={t(template.labelKey)}
            >
              {t(template.labelKey)}
            </Button>
            <p className="mt-2 text-sm text-content-secondary">{t(template.descriptionKey)}</p>
          </div>
        ))}
      </div>
    </WideModal>
    </span>
  );
}

export function BulgarianDemoCard() {
  const { t } = useTranslation();
  return (
    <section className="flex flex-col gap-4 rounded-xl border border-oe-blue/20 bg-oe-blue-subtle p-4 sm:flex-row sm:items-center sm:justify-between" aria-labelledby="bg-demo-title">
      <div className="min-w-0">
        <h2 id="bg-demo-title" className="flex items-center gap-2 text-sm font-semibold text-content-primary">
          <Building2 size={18} aria-hidden="true" />{t('bg_demo.title')}
        </h2>
        <p className="mt-1 max-w-3xl text-sm text-content-secondary">{t('bg_demo.description')}</p>
      </div>
      <BulgarianDemoLauncher />
    </section>
  );
}

export function BulgarianDemoGuide({ project }: { project: Project }) {
  const { t } = useTranslation();
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);
  if (!BULGARIAN_DEMOS.some((template) => template.demoId === project.metadata?.demo_id)) return null;
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
