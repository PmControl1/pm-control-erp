"""An explicit, owner-scoped Bulgarian walkthrough; never a boot-time seed.

The request transaction owns every database write. Locking the real owner's
row serializes simultaneous clicks across workers without a schema migration.
No credentials, contacts, outbound messages or shared catalogues are created.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.bulgarian_demo_templates import ADDITIONAL_TEMPLATES, DemoTemplate
from app.modules.boq.models import BOQ, BOQMarkup, Position
from app.modules.documents.models import Document
from app.modules.fieldreports.models import FieldReport
from app.modules.finance.models import Invoice, InvoiceLineItem, Payment, ProjectBudget
from app.modules.meetings.models import Meeting
from app.modules.projects.models import Project
from app.modules.punchlist.models import PunchItem
from app.modules.rfi.models import RFI
from app.modules.risk.models import RiskItem
from app.modules.schedule.models import Activity, Schedule, ScheduleRelationship
from app.modules.tasks.models import Task
from app.modules.teams.models import Team, TeamMembership
from app.modules.tendering.models import TenderBid, TenderPackage
from app.modules.users.models import User

DEMO_ID = "pm-bg-plovdiv-v1"
PROJECT_NAME = "ДЕМО — Жилищна сграда „Марица“, Пловдив"
NOTICE = (
    "Демонстрационни данни: всички участници, количества и цени са измислени. "
    "Не са пазарна оферта, официален строителен акт или счетоводен документ."
)

# Description, unit, quantity, unit rate; the hierarchy is Bulgarian KSS,
# deliberately independent of any foreign classification catalogue.
SECTIONS = (
    (
        "Подготовка и земни работи",
        (
            ("Организация на строителната площадка", "комплект", "1", "24000"),
            ("Машинен изкоп и извозване", "м³", "3200", "14"),
            ("Обратен насип с уплътняване", "м³", "600", "22"),
        ),
    ),
    (
        "Стоманобетонна конструкция",
        (
            ("Доставка и полагане на бетон C25/30", "м³", "980", "155"),
            ("Армировка B500B — доставка и монтаж", "т", "148", "1450"),
            ("Кофраж за стени, колони и плочи", "м²", "5200", "25"),
        ),
    ),
    (
        "Зидария и покрив",
        (
            ("Зидария от керамични блокове", "м²", "2400", "37"),
            ("Покривна топло- и хидроизолация", "м²", "700", "72"),
            ("Тенекеджийски обшивки", "м", "210", "28"),
        ),
    ),
    (
        "Фасада и дограма",
        (
            ("Фасадна топлоизолационна система", "м²", "2100", "58"),
            ("PVC дограма с троен стъклопакет", "м²", "620", "260"),
            ("Входни врати за апартаменти", "бр.", "24", "850"),
        ),
    ),
    (
        "ВиК, електро и ОВК",
        (
            ("ВиК инсталации — комплект за апартамент", "комплект", "24", "6500"),
            ("Електрически и слаботокови инсталации — комплект", "комплект", "24", "7200"),
            ("Отопление и подготовка за климатизация — комплект", "комплект", "24", "5800"),
            ("Пътнически асансьор — доставка и монтаж", "бр.", "1", "42000"),
        ),
    ),
    (
        "Довършителни работи",
        (
            ("Мазилки, шпакловки и боядисване", "м²", "9800", "12"),
            ("Циментова замазка", "м²", "3200", "18"),
            ("Настилки в общите части", "м²", "640", "48"),
        ),
    ),
    (
        "Двор и благоустрояване",
        (
            ("Настилки и алеи", "м²", "520", "46"),
            ("Озеленяване", "м²", "680", "24"),
            ("Дворно осветление и отводняване", "комплект", "1", "18000"),
        ),
    ),
)


RESIDENTIAL_TEMPLATE = DemoTemplate(
    key="residential",
    demo_id=DEMO_ID,
    name=PROJECT_NAME,
    project_code="DEMO-BG-001",
    project_type="residential",
    city="Пловдив",
    gross_floor_area="2400.000",
    description="24 апартамента; 2400 м² надземна РЗП и 600 м² сутерен. "
    "Роля на екипа: проектно управление и инвеститорски контрол.",
    sections=SECTIONS,
    phases=((-120, -91, 100), (-90, 10, 70), (11, 45, 0), (46, 105, 0), (46, 135, 0), (136, 190, 0), (191, 210, 0)),
    tender_section=3,
    invoice_section=1,
    invoice_fraction="0.4",
    invoice_payment_fraction="0.5",
    invoice_payment="120000",
    site_work={
        "task_titles": (
            "Проверка на междинното плащане DEMO-0001",
            "Сравнение на трите оферти за фасада и дограма",
            "Съгласуване на отворите за ВиК през плочата",
            "Повторна проверка на защитния бетонен слой",
            "Протокол от седмична оперативка",
        ),
        "meeting_title": "ДЕМО — седмична оперативка",
        "meeting_minutes": "1. Конструкция: 70% физически напредък, 40% фактурирани количества.\n"
        "2. Проверка на защитния слой преди бетониране.\n"
        "3. Сравнение на офертите за фасадата.",
        "rfi_subject": "Съгласуване на отвори за ВиК през плочата",
        "rfi_question": "Да се потвърдят размерите и разположението на отворите преди затваряне на кофража.",
        "rfi_discipline": "ВиК / Конструкции",
        "defect_title": "ДЕМО — недостатъчен защитен бетонен слой",
        "defect_description": "Плоча на кота +6.00: учебно проектно изискване 35 mm, измерени 25 mm. "
        "Да се поставят дистанционери и да се провери отново преди бетониране.",
        "defect_category": "Конструкция",
        "defect_trade": "Армировка",
        "risks": (
            (
                "Дълъг срок за доставка на асансьора",
                "0.4",
                "18000",
                20,
                "Ранно потвърждение на техническите параметри и писмен график за доставка.",
            ),
            (
                "Студено време при бетониране",
                "0.3",
                "12000",
                7,
                "Проверка на прогнозата, план за зимно бетониране и контрол на температурите.",
            ),
        ),
        "report_work": "ДЕМО — проверка на армировката и координация на ВиК отворите на кота +6.00.",
        "report_delay": "Бетонирането изчаква повторната проверка на защитния слой.",
    },
)
DEMO_TEMPLATES = {"residential": RESIDENTIAL_TEMPLATE, **ADDITIONAL_TEMPLATES}


def get_demo_template(template_id: str) -> DemoTemplate:
    """Resolve an explicit template before taking locks or writing any data."""
    template = DEMO_TEMPLATES.get(template_id)
    if template is None:
        raise HTTPException(status_code=422, detail="Unknown Bulgarian demo template")
    return template


class BulgarianDemoResponse(BaseModel):
    project_id: uuid.UUID
    project_name: str
    already_installed: bool
    template_id: str


def _money(value: Decimal | str) -> str:
    return format(Decimal(value).quantize(Decimal("0.01")), "f")


def _meta(template: DemoTemplate, **extra: object) -> dict:
    return {"demo_id": template.demo_id, "demo_template": template.key, "is_demo": True, **extra}


async def install_bulgarian_demo(
    session: AsyncSession,
    owner_id: uuid.UUID,
    *,
    template_id: str = "residential",
    today: date | None = None,
    upload_base: Path | None = None,
) -> BulgarianDemoResponse:
    """Create one active example per owner and template, preserving every edit.

    The endpoint requires authentication. This function also verifies the
    current account is active. It never commits: a failure rolls back all rows
    with the caller's transaction. An archived copy is left alone; an explicit
    later install creates a fresh example, without restoring archived content.
    """
    template = get_demo_template(template_id)
    owner = await session.scalar(select(User).where(User.id == owner_id).with_for_update())
    if owner is None or not owner.is_active or owner.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Active project owner not found")
    projects = (
        await session.scalars(select(Project).where(Project.owner_id == owner_id, Project.status != "archived"))
    ).all()
    existing = next((p for p in projects if (p.metadata_ or {}).get("demo_id") == template.demo_id), None)
    if existing:
        return BulgarianDemoResponse(
            project_id=existing.id, project_name=existing.name, already_installed=True, template_id=template.key
        )

    today = today or datetime.now(UTC).date()
    day = lambda offset: (today + timedelta(days=offset)).isoformat()  # noqa: E731
    totals = [
        sum((Decimal(qty) * Decimal(rate) for _, _, qty, rate in rows), Decimal(0)) for _, rows in template.sections
    ]
    net = sum(totals, Decimal(0))
    project = Project(
        id=uuid.uuid4(),
        name=template.name,
        description=f"{NOTICE} {template.description}",
        owner_id=owner_id,
        region="BG",
        country_code="BG",
        currency="EUR",
        locale="bg",
        classification_standard="",
        validation_rule_sets=["boq_quality", "bulgaria"],
        status="active",
        project_code=template.project_code,
        project_type=template.project_type,
        phase="construction",
        address={"city": template.city, "country": "България", "country_code": "BG"},
        planned_start_date=day(min(phase[0] for phase in template.phases)),
        planned_end_date=day(max(phase[1] for phase in template.phases)),
        actual_start_date=day(min(phase[0] for phase in template.phases)),
        budget_estimate=_money(net),
        contract_value=None,
        gross_floor_area=template.gross_floor_area,
        default_vat_rate="20",
        metadata_=_meta(template, demo_enrichment=False, snapshot_date=today.isoformat()),
    )
    session.add(project)
    await session.flush()
    team = Team(
        id=uuid.uuid4(),
        project_id=project.id,
        name="ДЕМО — екип на проекта",
        is_default=True,
        metadata_=_meta(template),
    )
    session.add(team)
    await session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=owner_id, role="lead"))
    boq = BOQ(
        id=uuid.uuid4(),
        project_id=project.id,
        name="ДЕМО — КСС за строителството",
        description=NOTICE,
        status="draft",
        created_by=owner_id,
        base_date=today.isoformat(),
        metadata_=_meta(template),
    )
    session.add(boq)
    await session.flush()
    positions: list[list[Position]] = []
    for index, (title, rows) in enumerate(template.sections, 1):
        section = Position(
            id=uuid.uuid4(),
            boq_id=boq.id,
            ordinal=f"{index:02}",
            description=title,
            unit="",
            quantity="0",
            unit_rate="0",
            total="0",
            sort_order=index * 100,
            source="template",
            metadata_=_meta(template),
        )
        session.add(section)
        await session.flush()
        lines = []
        for line_index, (description, unit, quantity, rate) in enumerate(rows, 1):
            line = Position(
                id=uuid.uuid4(),
                boq_id=boq.id,
                parent_id=section.id,
                ordinal=f"{index:02}.{line_index:02}",
                description=description,
                unit=unit,
                quantity=f"{Decimal(quantity):.3f}",
                unit_rate=_money(rate),
                total=_money(Decimal(quantity) * Decimal(rate)),
                source="template",
                validation_status="pending",
                sort_order=index * 100 + line_index,
                metadata_=_meta(template, currency="EUR", price_note=NOTICE),
            )
            session.add(line)
            lines.append(line)
        positions.append(lines)
        session.add(
            ProjectBudget(
                project_id=project.id,
                category=title,
                currency_code="EUR",
                original_budget=totals[index - 1],
                revised_budget=totals[index - 1],
                actual=Decimal(0),
                committed=Decimal(0),
                forecast_final=totals[index - 1],
                metadata_=_meta(
                    template,
                    basis="net",
                    note="Платени и оставащи задължения без ДДС, изчислени от фактурите и плащанията.",
                ),
            )
        )
    session.add(
        BOQMarkup(
            boq_id=boq.id,
            name="ДДС (демо) 20%",
            category="tax",
            percentage="20",
            apply_to="cumulative",
            sort_order=1,
            metadata_=_meta(template),
        )
    )
    await session.flush()

    schedule = Schedule(
        id=uuid.uuid4(),
        project_id=project.id,
        name="ДЕМО — основен график",
        description=f"{NOTICE} Физически напредък към {today.isoformat()}; фактурирането е отделен показател.",
        start_date=day(min(phase[0] for phase in template.phases)),
        end_date=day(max(phase[1] for phase in template.phases)),
        data_date=today.isoformat(),
        status="active",
        created_by=owner_id,
        metadata_=_meta(template),
    )
    session.add(schedule)
    await session.flush()
    activities = []
    for index, ((title, _), (start, end, progress)) in enumerate(zip(template.sections, template.phases, strict=True)):
        activity = Activity(
            id=uuid.uuid4(),
            schedule_id=schedule.id,
            name=title,
            wbs_code=f"{index + 1:02}",
            start_date=day(start),
            end_date=day(end),
            duration_days=end - start + 1,
            progress_pct=str(progress),
            status="completed" if progress == 100 else "in_progress" if progress else "not_started",
            sort_order=index,
            boq_position_ids=[str(p.id) for p in positions[index]],
            metadata_=_meta(template),
        )
        activities.append(activity)
        session.add(activity)
    await session.flush()
    for before, after in template.dependencies:
        session.add(
            ScheduleRelationship(
                schedule_id=schedule.id,
                predecessor_id=activities[before].id,
                successor_id=activities[after].id,
                relationship_type="FS",
                metadata_=_meta(template),
            )
        )

    tender = TenderPackage(
        id=uuid.uuid4(),
        project_id=project.id,
        boq_id=boq.id,
        name=f"ДЕМО — избор на изпълнител: {template.sections[template.tender_section][0].lower()}",
        description=f"{NOTICE} Сравнете цена и срок; изборът е отворен.",
        status="evaluating",
        deadline=day(-1),
        metadata_=_meta(
            template, scope_position_ids=[str(p.id) for p in positions[template.tender_section]], currency="EUR"
        ),
    )
    session.add(tender)
    await session.flush()
    for company, factor, duration in zip(
        ("А", "Б", "В"), ("0.98", "1.04", "0.96"), template.bid_durations, strict=True
    ):
        lines = [
            {
                "position_id": str(p.id),
                "description": p.description,
                "unit": p.unit,
                "quantity": p.quantity,
                "unit_rate": _money(Decimal(p.unit_rate) * Decimal(factor)),
                "total": _money(Decimal(p.quantity) * Decimal(_money(Decimal(p.unit_rate) * Decimal(factor)))),
            }
            for p in positions[template.tender_section]
        ]
        session.add(
            TenderBid(
                package_id=tender.id,
                company_name=f"ДЕМО {template.tender_company_label} {company}",
                contact_email="",
                currency="EUR",
                total_amount=_money(sum((Decimal(line["total"]) for line in lines), Decimal(0))),
                submitted_at=day(-3),
                status="submitted",
                line_items=lines,
                notes=f"{NOTICE} Срок: {duration} календарни дни. Всички позиции са включени; суми без ДДС.",
                metadata_=_meta(template, duration_days=duration),
            )
        )

    invoice_net = totals[template.invoice_section] * Decimal(template.invoice_fraction)
    invoice_gross = invoice_net * Decimal("1.2")
    partial_payment = (
        Decimal(template.invoice_payment)
        if template.invoice_payment is not None
        else (invoice_gross * Decimal(template.invoice_payment_fraction)).quantize(Decimal("0.01"))
    )
    for invoice_index, (section_index, fraction, paid) in enumerate(
        [
            (0, Decimal(1), totals[0] * Decimal("1.2")),
            (template.invoice_section, Decimal(template.invoice_fraction), partial_payment),
        ]
    ):
        subtotal = totals[section_index] * fraction
        invoice = Invoice(
            id=uuid.uuid4(),
            project_id=project.id,
            invoice_direction="payable",
            invoice_number=f"DEMO-{invoice_index:04}",
            invoice_date=day(-30 if invoice_index == 0 else -7),
            due_date=day(-16 if invoice_index == 0 else 7),
            currency_code="EUR",
            amount_subtotal=subtotal,
            tax_amount=subtotal * Decimal("0.2"),
            amount_total=subtotal * Decimal("1.2"),
            status="paid" if invoice_index == 0 else "approved",
            created_by=owner_id,
            notes=f"{NOTICE} ДЕМО изпълнител. Междинно плащане за {template.sections[section_index][0].lower()}.",
            metadata_=_meta(template),
        )
        session.add(invoice)
        await session.flush()
        for index, position in enumerate(positions[section_index]):
            session.add(
                InvoiceLineItem(
                    invoice_id=invoice.id,
                    description=position.description,
                    quantity=Decimal(position.quantity) * fraction,
                    unit=position.unit,
                    unit_rate=Decimal(position.unit_rate),
                    amount=Decimal(position.total) * fraction,
                    vat_rate=Decimal(20),
                    vat_category="S",
                    cost_category=template.sections[section_index][0],
                    sort_order=index,
                )
            )
        session.add(
            Payment(
                invoice_id=invoice.id,
                payment_date=day(-20 if invoice_index == 0 else -2),
                amount=paid,
                currency_code="EUR",
                reference="ДЕМО — примерен запис, без банков превод",
                metadata_=_meta(template),
            )
        )

    _add_site_work(session, project.id, owner_id, today, template)
    await session.flush()
    # Use the same source markers as later payment edits, so opening the
    # walkthrough and changing an invoice cannot double-post these actuals.
    from app.modules.finance.service import FinanceService

    await FinanceService(session).sync_project_budget(project.id)
    if upload_base is None:
        from app.modules.documents.service import UPLOAD_BASE

        upload_base = UPLOAD_BASE
    _add_documents(session, project, boq, positions, today, upload_base, template, partial_payment)
    await session.flush()
    return BulgarianDemoResponse(
        project_id=project.id, project_name=project.name, already_installed=False, template_id=template.key
    )


def _add_site_work(
    session: AsyncSession, project_id: uuid.UUID, owner_id: uuid.UUID, today: date, template: DemoTemplate
) -> None:
    from app.modules.risk.service import _compute_risk_tier, _probability_to_score

    def day(offset: int) -> str:
        return (today + timedelta(days=offset)).isoformat()

    work = template.site_work
    meeting = Meeting(
        id=uuid.uuid4(),
        project_id=project_id,
        meeting_number="DEMO-01",
        meeting_type="coordination",
        title=work["meeting_title"],
        meeting_date=day(-2),
        location=f"{template.city} — учебен обект",
        chairperson_id=owner_id,
        status="completed",
        created_by=str(owner_id),
        minutes=f"{NOTICE}\n{work['meeting_minutes']}",
        metadata_=_meta(template),
    )
    session.add(meeting)
    task_states = [
        (3, "in_progress", "high"),
        (7, "open", "normal"),
        (4, "open", "high"),
        (1, "in_progress", "urgent"),
        (-2, "completed", "normal"),
    ]
    for title, (offset, status, priority) in zip(work["task_titles"], task_states, strict=True):
        session.add(
            Task(
                project_id=project_id,
                task_type="task",
                title=title,
                description=NOTICE,
                due_date=day(offset),
                status=status,
                priority=priority,
                created_by=str(owner_id),
                responsible_id=owner_id,
                meeting_id=str(meeting.id),
                metadata_=_meta(template),
            )
        )
    session.add(
        RFI(
            project_id=project_id,
            rfi_number="DEMO-RFI-01",
            subject=work["rfi_subject"],
            question=f"{NOTICE} {work['rfi_question']}",
            raised_by=owner_id,
            assigned_to=owner_id,
            status="open",
            priority="high",
            discipline=work["rfi_discipline"],
            date_required=day(4),
            response_due_date=day(4),
            created_by=str(owner_id),
            metadata_=_meta(template),
        )
    )
    session.add(
        PunchItem(
            project_id=project_id,
            title=work["defect_title"],
            description=f"{NOTICE} {work['defect_description']}",
            priority="high",
            status="open",
            due_date=datetime.combine(today + timedelta(days=1), time(), UTC),
            category=work["defect_category"],
            trade=work["defect_trade"],
            created_by=str(owner_id),
            assigned_to=str(owner_id),
            rework_cost_currency="EUR",
            metadata_=_meta(template),
        )
    )
    for index, (title, probability, cost, delay, mitigation) in enumerate(work["risks"], 1):
        probability_score = _probability_to_score(float(probability))
        session.add(
            RiskItem(
                project_id=project_id,
                code=f"DEMO-R-{index:02}",
                title=title,
                description=NOTICE,
                probability=probability,
                impact_cost=cost,
                impact_schedule_days=delay,
                impact_severity="high",
                risk_score=str(Decimal(probability) * 4),
                status="identified",
                currency="EUR",
                probability_score=probability_score,
                impact_score_cost=4,
                impact_score_time=4,
                risk_tier=_compute_risk_tier(probability_score, 4),
                mitigation_strategy=mitigation,
                owner_user_id=owner_id,
                owner_name="Ръководител на демо проекта",
                metadata_=_meta(template),
            )
        )
    session.add(
        FieldReport(
            project_id=project_id,
            report_date=today - timedelta(days=1),
            status="draft",
            weather_condition="clear",
            temperature_c=12,
            created_by=owner_id,
            work_performed=work["report_work"],
            notes=NOTICE,
            delays=work["report_delay"],
            metadata_=_meta(template),
        )
    )


def _add_documents(
    session: AsyncSession,
    project: Project,
    boq: BOQ,
    positions: list[list[Position]],
    today: date,
    upload_base: Path,
    template: DemoTemplate,
    partial_payment: Decimal,
) -> None:
    """Store actual downloadable UTF-8 files, not document-register placeholders."""
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Код", "Описание", "Мярка", "Количество", "Ед. цена EUR без ДДС", "Общо EUR без ДДС"])
    for section in positions:
        for position in section:
            writer.writerow(
                [
                    position.ordinal,
                    position.description,
                    position.unit,
                    position.quantity,
                    position.unit_rate,
                    position.total,
                ]
            )

    def euro(value: Decimal) -> str:
        return f"{value:,.2f}".replace(",", " ").replace(".", ",")

    net = sum((Decimal(p.total) for section in positions for p in section), Decimal(0))
    fraction = Decimal(template.invoice_fraction)
    invoiced_positions = positions[template.invoice_section]
    invoice_net = sum((Decimal(p.total) * fraction for p in invoiced_positions), Decimal(0))
    invoice_tax = invoice_net * Decimal("0.2")
    invoice_gross = invoice_net + invoice_tax
    invoice_scope = template.sections[template.invoice_section][0]
    tender_scope = template.sections[template.tender_section][0]
    payment_lines = "\n".join(
        f"{p.description}: {Decimal(p.quantity) * fraction:.3f} {p.unit} × {euro(Decimal(p.unit_rate))} EUR "
        f"= {euro(Decimal(p.total) * fraction)} EUR"
        for p in invoiced_positions
    )
    progress = "; ".join(
        f"{title}: {phase[2]}%" for (title, _), phase in zip(template.sections, template.phases, strict=True)
    )
    files = [
        ("DEMO-KSS.csv", "text/csv", "estimate", output.getvalue()),
        (
            "DEMO-project-guide.txt",
            "text/plain",
            "other",
            f"{project.name}\n{NOTICE}\n{template.description}\n\n"
            f"Снимка на проекта към {today.isoformat()}.\n"
            f"1. КСС: {sum(map(len, positions))} позиции в {len(positions)} раздела, {euro(net)} EUR без ДДС.\n"
            f"2. График: {progress}.\n"
            f"3. Търгове: три сравними оферти за {tender_scope.lower()}; оценяването е отворено.\n"
            f"4. Финанси: DEMO-0001 — {euro(invoice_net)} EUR без ДДС, {euro(invoice_gross)} EUR с ДДС; "
            f"примерно платени {euro(partial_payment)} EUR, остатък {euro(invoice_gross - partial_payment)} EUR.\n"
            f"5. Координация: {template.site_work['rfi_subject']}.\n"
            "6. Всеки потребител отваря собствен демо проект от избора на проект в приложението.\n"
            "Достъпът и редактирането следват правата на профила; повторно отваряне запазва редакциите.\n",
        ),
        (
            "DEMO-payment-review.txt",
            "text/plain",
            "financial",
            f"ДЕМО — проверка на плащане\n{project.name}\n{NOTICE}\n\n"
            f"Учебна проверка на DEMO-0001 — {invoice_scope.lower()}\n{payment_lines}\n"
            f"Нетно: {euro(invoice_net)} EUR; примерен ДДС 20%: {euro(invoice_tax)} EUR; "
            f"общо: {euro(invoice_gross)} EUR.\n"
            f"Примерно платени: {euro(partial_payment)} EUR; неплатени: {euro(invoice_gross - partial_payment)} EUR.\n"
            f"{fraction * 100:g}% фактурирани количества не означава същия физически напредък.\n",
        ),
    ]
    directory = upload_base / "bulgarian-demo" / str(project.id)
    directory.mkdir(parents=True, exist_ok=False)
    # Files belong to the same transaction as the register rows. In particular,
    # a failure during the final flush/commit must not leave orphaned downloads.
    sync_session = session.sync_session
    transaction = sync_session.get_transaction()
    nested_transaction = sync_session.get_nested_transaction()
    committed = False

    def cleanup() -> None:
        for filename, *_ in files:
            (directory / filename).unlink(missing_ok=True)
        if directory.exists():
            directory.rmdir()

    @event.listens_for(sync_session, "after_commit")
    def mark_committed(current_session) -> None:
        nonlocal committed
        current = current_session.get_nested_transaction() or current_session.get_transaction()
        if current is transaction:
            committed = True

    @event.listens_for(sync_session, "after_soft_rollback")
    def cleanup_rolled_back_files(_current_session, previous_transaction) -> None:
        if not committed and previous_transaction in (transaction, nested_transaction):
            cleanup()

    try:
        for filename, mime_type, category, content in files:
            payload = ("\ufeff" + content).encode("utf-8")
            path = directory / filename
            path.write_bytes(payload)
            session.add(
                Document(
                    project_id=project.id,
                    name=filename,
                    description=NOTICE,
                    category=category,
                    file_size=len(payload),
                    mime_type=mime_type,
                    file_path=str(path.resolve()),
                    uploaded_by=str(project.owner_id),
                    tags=["ДЕМО", "България"],
                    metadata_=_meta(template, boq_id=str(boq.id)),
                )
            )
    except Exception:
        cleanup()
        raise
