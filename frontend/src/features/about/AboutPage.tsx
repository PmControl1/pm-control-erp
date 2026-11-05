// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Modified 2026 for PM Project Management: upstream's About page (project
// story, sponsors, donation and community links) is replaced by the product
// identity, the licence notice and the upstream credit that AGPL-3.0 and the
// upstream trademark policy call for.
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation } from 'react-router-dom';
import { Card, Badge, Breadcrumb } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { Logo } from '@/shared/ui/Logo';
import { APP_VERSION } from '@/shared/lib/version';
import {
  BRAND_NAME,
  BRAND_SOURCE_URL,
  BRAND_SUPPORT_EMAIL,
  TEST_BUILD,
  UPSTREAM_AUTHOR,
  UPSTREAM_NAME,
  UPSTREAM_SOURCE_URL,
} from '@/shared/brand';
import { Changelog } from './Changelog';
import { ThirdPartyLicenses } from './ThirdPartyLicenses';

const AGPL_URL = 'https://www.gnu.org/licenses/agpl-3.0.html';

export function AboutPage() {
  const { t } = useTranslation();

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb items={[{ label: t('nav.about', { defaultValue: 'About' }) }]} />
      <PageHeader srTitle={t('nav.about', { defaultValue: 'About' })} />

      <Card>
        <div className="flex flex-col sm:flex-row sm:items-center gap-5">
          <Logo size="xl" />
          <div className="min-w-0">
            <h2 className="text-2xl font-bold text-content-primary tracking-tight">{BRAND_NAME}</h2>
            <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-content-tertiary">
              <span className="font-mono">v{APP_VERSION}</span>
              {!TEST_BUILD && (
                <>
                  <span>&middot;</span>
                  <Badge variant="blue" size="sm">AGPL-3.0</Badge>
                </>
              )}
            </div>
            {BRAND_SUPPORT_EMAIL && (
              <p className="mt-2 text-sm text-content-secondary">
                {t('about.support_contact', { defaultValue: 'Support' })}:{' '}
                <a className="text-oe-blue hover:underline" href={`mailto:${BRAND_SUPPORT_EMAIL}`}>
                  {BRAND_SUPPORT_EMAIL}
                </a>
              </p>
            )}
          </div>
        </div>
      </Card>
      <ReleaseDetails />
    </div>
  );
}

function ReleaseDetails() {
  const { t } = useTranslation();
  const { hash, key } = useLocation();
  const [changelogExpanded, setChangelogExpanded] = useState(false);

  // /about#changelog (header and sidebar "what's new" links) opens the full list.
  useEffect(() => {
    if (hash !== '#changelog') return;
    setChangelogExpanded(true);
    const frame = window.requestAnimationFrame(() => {
      document
        .querySelector('[data-changelog-anchor]')
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [hash, key]);

  return (
    <>
      {!TEST_BUILD && <Card>
        <h3 className="text-base font-semibold text-content-primary mb-3">
          {t('about.licence_title', { defaultValue: 'Licence and credits' })}
        </h3>
        <div className="space-y-3 text-sm text-content-secondary leading-relaxed">
          <p>
            {BRAND_NAME} is based on{' '}
            <a
              data-upstream-credit
              className="text-oe-blue hover:underline"
              href={UPSTREAM_SOURCE_URL}
              target="_blank"
              rel="noopener noreferrer"
            >
              {UPSTREAM_NAME}
            </a>
            , Copyright &copy; 2026 {UPSTREAM_AUTHOR}. This product is not affiliated with, endorsed
            by, or sponsored by DataDrivenConstruction.
          </p>
          <p>
            This program is free software: you can redistribute it and/or modify it under the terms
            of the{' '}
            <a
              className="text-oe-blue hover:underline"
              href={AGPL_URL}
              target="_blank"
              rel="noopener noreferrer"
            >
              GNU Affero General Public License
            </a>{' '}
            as published by the Free Software Foundation, either version 3 of the License, or (at
            your option) any later version. It is distributed in the hope that it will be useful,
            but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
            FITNESS FOR A PARTICULAR PURPOSE.
          </p>
          <p>
            {BRAND_SOURCE_URL ? (
              <>
                The complete source code of this version is available at{' '}
                <a
                  className="text-oe-blue hover:underline break-all"
                  href={BRAND_SOURCE_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {BRAND_SOURCE_URL}
                </a>
                .
              </>
            ) : (
              <>
                The complete source code of this version is available from {BRAND_NAME} on
                request.
              </>
            )}
          </p>
        </div>
      </Card>}

      {!TEST_BUILD && <Card>
        <h3 className="text-base font-semibold text-content-primary mb-3">
          {t('about.third_party_title', { defaultValue: 'Third-party software' })}
        </h3>
        <ThirdPartyLicenses />
      </Card>}

      <Card>
        <div className="p-2" data-changelog-anchor>
          <Changelog maxEntries={changelogExpanded ? undefined : 1} />
          <div className="mt-4 flex justify-center">
            <button
              type="button"
              onClick={() => setChangelogExpanded((v) => !v)}
              className="text-sm font-medium text-oe-blue hover:underline"
            >
              {changelogExpanded
                ? t('about.changelog_collapse', { defaultValue: 'Show less' })
                : t('about.changelog_expand', { defaultValue: 'Show full history' })}
            </button>
          </div>
        </div>
      </Card>
    </>
  );
}
