// The project form offers the classifications the country's pack declares,
// in the reader's language, and only the values the server will accept.
//
// The i18n mock in src/test/setup.ts returns the defaultValue with its
// placeholders filled in, and reports English as the language.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn() };
});

import { apiGet } from '@/shared/lib/api';
import { chosenClassifications } from './CreateProjectPage';
import { ProjectClassificationFields, type ProjectClassificationsResponse } from './ProjectClassificationFields';

const ZUT: ProjectClassificationsResponse = {
  country: 'BG',
  pack_slug: 'bulgaria-bg',
  locale: 'bg',
  source: 'active_pack',
  classifications: [
    {
      key: 'bg_zut_category',
      label: 'Категория по ЗУТ',
      label_en: 'Construction category (ZUT)',
      statute: 'ЗУТ чл. 137, ал. 1',
      help: 'Категорията определя кой издава разрешението за строеж.',
      help_en: 'The category decides who issues the building permit.',
      options: ['I', 'II', 'III', 'IV', 'V', 'VI'].map((value) => ({
        value,
        label: `${value} категория`,
        label_en: `Category ${value}`,
        hint: `Пояснение ${value}`,
        hint_en: `Hint ${value}`,
      })),
    },
  ],
};

function renderField(values: Record<string, unknown>, onChange = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ProjectClassificationFields
        idPrefix="test"
        region="Bulgaria"
        countryCode={null}
        values={values}
        onChange={onChange}
      />
    </QueryClientProvider>,
  );
  return onChange;
}

describe('ProjectClassificationFields', () => {
  beforeEach(() => {
    vi.mocked(apiGet).mockReset();
  });

  it('offers the six ЗУТ categories for a Bulgarian project, glossed for an English reader', async () => {
    vi.mocked(apiGet).mockResolvedValue(ZUT);
    renderField({});

    const select = await screen.findByLabelText('Construction category (ZUT)');
    const options = Array.from((select as HTMLSelectElement).options).map((o) => o.textContent);
    expect(options).toEqual([
      'Not recorded',
      'Category I',
      'Category II',
      'Category III',
      'Category IV',
      'Category V',
      'Category VI',
    ]);
    expect(screen.getByText('The category decides who issues the building permit.')).toBeInTheDocument();
    expect(screen.getByText('Set by ЗУТ чл. 137, ал. 1')).toBeInTheDocument();
    expect(vi.mocked(apiGet)).toHaveBeenCalledWith('/v1/partner-pack/project-classifications?region=Bulgaria');
  });

  it('reports the chosen category and explains it', async () => {
    vi.mocked(apiGet).mockResolvedValue(ZUT);
    const onChange = renderField({ bg_zut_category: 'III' });

    const select = await screen.findByLabelText('Construction category (ZUT)');
    expect(select).toHaveValue('III');
    expect(screen.getByText('Hint III')).toBeInTheDocument();

    fireEvent.change(select, { target: { value: 'V' } });
    expect(onChange).toHaveBeenCalledWith('bg_zut_category', 'V');
    fireEvent.change(select, { target: { value: '' } });
    expect(onChange).toHaveBeenCalledWith('bg_zut_category', null);
  });

  it('renders nothing for a country no pack files projects for', async () => {
    vi.mocked(apiGet).mockResolvedValue({ ...ZUT, country: 'HU', pack_slug: null, locale: null, classifications: [] });
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <ProjectClassificationFields idPrefix="t" region="HU" countryCode="HU" values={{}} onChange={vi.fn()} />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(vi.mocked(apiGet)).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('asks nothing before the project has a region or a country', () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ProjectClassificationFields idPrefix="t" region="" countryCode={null} values={{}} onChange={vi.fn()} />
      </QueryClientProvider>,
    );
    expect(vi.mocked(apiGet)).not.toHaveBeenCalled();
  });
});

describe('chosenClassifications', () => {
  it('sends only chosen values, and nothing when none was chosen', () => {
    expect(chosenClassifications({})).toBeUndefined();
    expect(chosenClassifications({ bg_zut_category: null })).toBeUndefined();
    expect(chosenClassifications({ bg_zut_category: 'IV', other: null })).toEqual({ bg_zut_category: 'IV' });
  });
});
