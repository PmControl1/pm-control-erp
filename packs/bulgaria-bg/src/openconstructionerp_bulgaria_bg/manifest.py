"""Build the ``PartnerPackManifest`` instance for the bulgaria-bg pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import (
    ClassificationOption,
    CompanyIdentifierSpec,
    PartnerBranding,
    PartnerPackManifest,
    ProjectClassificationSpec,
)

#: ЗУТ чл. 137, ал. 1 sorts every construction into one of six categories by
#: its characteristics, significance, complexity and operational risk, and
#: Наредба № 1 от 30.07.2003 г. за номенклатурата на видовете строежи details
#: which works fall in which. The category decides who approves the design and
#: issues the permit, whether a licensed consultant (строителен надзор) must
#: supervise, and whether the building is put into service by the ДНСК
#: (разрешение за ползване, I to III) or by the municipality (удостоверение за
#: въвеждане в експлоатация, IV and V). Category VI needs neither. A строеж
#: that falls in two categories by different criteria takes the higher one.
#: The hints are summaries for choosing, not the statute: the full criteria,
#: thresholds included, are in чл. 137 and the Наредба.
ZUT_CATEGORIES = ProjectClassificationSpec(
    key="bg_zut_category",
    label="Категория по ЗУТ",
    label_en="Construction category (ZUT)",
    statute="ЗУТ чл. 137, ал. 1; Наредба № 1 от 30.07.2003 г.",
    help=(
        "Категорията определя кой одобрява проекта и издава разрешението за строеж, дали е "
        "задължителен строителен надзор от консултант и кой въвежда строежа в експлоатация. "
        "Строеж, който по различни критерии попада в две категории, е от по-високата."
    ),
    help_en=(
        "The category decides who approves the design and issues the building permit, whether a "
        "licensed consultant must supervise, and who puts the works into service. Works that fall "
        "in two categories by different criteria take the higher one."
    ),
    options=[
        ClassificationOption(
            value="I",
            label="I категория",
            label_en="Category I",
            hint=(
                "Строежи с национално значение и с най-висока сложност, вкл. техническа "
                "инфраструктура с национално значение (чл. 137, ал. 1, т. 1). Надзор от "
                "консултант; разрешение за ползване от ДНСК."
            ),
            hint_en=(
                "Works of national significance and the highest complexity, including national "
                "technical infrastructure. Consultant supervision; use permit from the DNSK."
            ),
        ),
        ClassificationOption(
            value="II",
            label="II категория",
            label_en="Category II",
            hint=(
                "Големи строежи на техническата инфраструктура и сгради с голям капацитет "
                "(чл. 137, ал. 1, т. 2). Надзор от консултант; разрешение за ползване от ДНСК."
            ),
            hint_en=(
                "Large technical infrastructure and high-capacity buildings. Consultant "
                "supervision; use permit from the DNSK."
            ),
        ),
        ClassificationOption(
            value="III",
            label="III категория",
            label_en="Category III",
            hint=(
                "Вкл. жилищни и смесени сгради с високо застрояване и сгради за обществено "
                "обслужване с РЗП над 5000 м² (чл. 137, ал. 1, т. 3). Надзор от консултант; "
                "разрешение за ползване от ДНСК."
            ),
            hint_en=(
                "Including high-rise residential and mixed-use buildings and public buildings over "
                "5,000 m² GFA. Consultant supervision; use permit from the DNSK."
            ),
        ),
        ClassificationOption(
            value="IV",
            label="IV категория",
            label_en="Category IV",
            hint=(
                "Жилищни и смесени сгради със средно застрояване; сгради за обществено обслужване "
                "с РЗП 1000–5000 м² или 100–200 места; частни пътища и улици V и VI клас; вътрешни "
                "преустройства на сгради I–IV кат. без засягане на конструкцията. Надзор от "
                "консултант; удостоверение за въвеждане в експлоатация от общината."
            ),
            hint_en=(
                "Medium-rise residential and mixed-use buildings; public buildings of 1,000-5,000 m² "
                "or 100-200 places; private roads and class V-VI streets; internal alterations "
                "that leave the structure untouched. Consultant supervision; certificate of "
                "putting into service from the municipality."
            ),
        ),
        ClassificationOption(
            value="V",
            label="V категория",
            label_en="Category V",
            hint=(
                "Жилищни и смесени сгради с ниско застрояване, вилни сгради; сгради за обществено "
                "обслужване с РЗП до 1000 м² или до 100 места; производствени сгради до 50 работни "
                "места; допълващо застрояване извън VI кат. Удостоверение за въвеждане в "
                "експлоатация от общината."
            ),
            hint_en=(
                "Low-rise residential and mixed-use buildings and holiday homes; public buildings "
                "up to 1,000 m² or 100 places; production buildings up to 50 workplaces; ancillary "
                "buildings outside category VI. Certificate of putting into service from the "
                "municipality."
            ),
        ),
        ClassificationOption(
            value="VI",
            label="VI категория",
            label_en="Category VI",
            hint=(
                "Строежите по чл. 54, ал. 1 и 4 и чл. 147 ЗУТ: допълващо застрояване, монтаж на "
                "инсталации и съоръжения, огради, временни строежи и др. Не се въвеждат в "
                "експлоатация с разрешение или удостоверение за ползване."
            ),
            hint_en=(
                "Works under ZUT art. 54(1) and (4) and art. 147: ancillary structures, installing "
                "equipment, fences, temporary works and similar. No use permit or certificate."
            ),
        ),
    ],
)

MANIFEST = PartnerPackManifest(
    slug="bulgaria-bg",
    partner_name="Bulgaria Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for Bulgarian contractors, consultants and investors: the КСС "
        "(priced bill of quantities) with all-in unit rates and ДДС at 20 % added once, in "
        "euro since 1 January 2026 with lev amounts converted at the fixed 1.95583, the "
        "company ЕИК on the letterhead checked by its check digit, the six ЗУТ construction "
        "categories on every Bulgarian project, the Sofia cost database, and a Bulgarian "
        "interface whose construction vocabulary is fixed to the trade's own words."
    ),
    # The interface ships a Bulgarian bundle; the pack's overlay fixes how it
    # names the bill and a few modules (tools/build_vocabulary.py says how).
    default_locale="bg",
    additional_locales={"bg": "locales/bg.json"},
    # BG_SOFIA was published in lev. It still loads into a euro workspace: the
    # lev is fixed to the euro at 1.95583 (app.core.euro_conversion), so every
    # rate converts by law, and a Bulgarian euro project starts with that rate
    # in its own table.
    cwicr_regions=[
        "cwicr-bg-sofia",
    ],
    # Bulgaria adopted the euro on 2026-01-01 (Council Decision (EU) 2025/1407,
    # Council Regulation (EU) 2025/1409).
    default_currency="EUR",
    # Documentation only. ДДС 20 % comes from the platform's dated tax table
    # (code DDS, default since 1999-01-01) and from the BG markup stack, a
    # single ДДС line: a КСС carries overheads and profit inside every rate.
    default_tax_template=None,
    default_methodology="bulgaria",
    validation_rule_packs=[
        "bg_kss",
        "bg_zut",
        "bg_zop",
        "bg_dds",
        "bg_evro",
    ],
    # DIN 276 is the nearest hierarchy the platform supports for a Bulgarian
    # bill, the same choice the Croatian, Czech and Romanian packs make; it is
    # what the classification registry already answers for BG.
    validation_rule_sets=[
        "din276",
    ],
    default_modules=[],  # empty = show all
    hidden_modules=[],
    # One Bulgarian demo so far: a residential block in Sofia, III category.
    demo_template_ids=["residential-sofia"],
    company_identifier=CompanyIdentifierSpec(
        scheme="eik",
        label="ЕИК",
        label_en="UIC (ЕИК / BULSTAT)",
        placeholder="123456786",
        help=(
            "Единен идентификационен код от Търговския регистър или регистър БУЛСТАТ: 9 цифри, "
            "или 13 за клон. Проверява се по контролната цифра и се отпечатва в бланката."
        ),
    ),
    project_classifications=[ZUT_CATEGORIES],
    branding=PartnerBranding(
        primary_color="#00966E",  # green of the national flag
        accent_color="#D62612",  # red of the national flag
        logo_path=None,  # no partner logo; the UI draws the country monogram
        favicon_path=None,
        powered_by_text=None,  # use default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "BG",
        "country_name_en": "Bulgaria",
        "country_name_bg": "България",
        "classification_standard": "din276",
        "legacy_currency": {
            "code": "BGN",
            "per_euro": "1.95583",
            "euro_since": "2026-01-01",
            "rule": "ЗВЕРБ чл. 12: divide by the rate as published, round the euro amount half up to the cent",
        },
        "regulator_refs": [
            "Закон за устройство на територията (ЗУТ), чл. 137 - категории на строежите",
            "Наредба № 1 от 30.07.2003 г. за номенклатурата на видовете строежи",
            "Наредба № 3 от 31.07.2003 г. за съставяне на актове и протоколи по време на строителството",
            "Закон за обществените поръчки (ЗОП)",
            "Закон за данък върху добавената стойност (ЗДДС), чл. 66",
            "Закон за въвеждане на еврото в Република България (ЗВЕРБ)",
            "Council Regulation (EU) 2025/1409, conversion rate of the lev",
            "Закон за търговския регистър и регистъра на юридическите лица с нестопанска цел; Закон за регистър БУЛСТАТ",
        ],
        # The order a Bulgarian КСС commonly follows for a building. Every line
        # carries an all-in единична цена and the сметка closes with "Общо без
        # ДДС", "ДДС 20 %" and "Всичко с ДДС".
        "kss_sections": [
            "Подготвителни работи (Preliminary works)",
            "Земни работи (Earthworks)",
            "Кофражни, армировъчни и бетонови работи (Formwork, reinforcement and concrete)",
            "Зидарски работи (Masonry)",
            "Хидроизолации и топлоизолации (Waterproofing and insulation)",
            "Покривни и тенекеджийски работи (Roofing and sheet metal)",
            "Дограма (Windows and doors)",
            "Довършителни работи: мазилки, шпакловки, бояджийски, облицовки, настилки (Finishes)",
            "Фасадни работи (Façade)",
            "ВиК инсталации (Plumbing and drainage)",
            "Електрически инсталации (Electrical)",
            "ОВК инсталации (HVAC)",
            "Вертикална планировка и благоустрояване (External works)",
        ],
        "vat_standard_rate": 20,
        "vat_reduced_rate": 9,
        "vat_rates": [20, 9, 0],
        "review_status": (
            "Currency, conversion rule, tax rates, the ЕИК check digit and the ЗУТ category "
            "list are drawn from public sources read on 2026-10-31. The category hints are "
            "summaries for choosing and the КСС section order reflects common Bulgarian practice; "
            "both are pending review by a Bulgarian quantity surveyor (инженер-сметчик) before "
            "they are relied on for a public tender."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
