"""The Bulgarian product creates a project, imports a КСС and exports its totals."""

from __future__ import annotations

import io
import uuid
from decimal import Decimal

import pypdf
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook, load_workbook

from app.main import create_app


@pytest_asyncio.fixture(scope="module")
async def bulgarian_client():
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SEED_DEMO", "false")
        app = create_app()
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                yield client


def _lev_bill() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "КСС"
    sheet.append(["КОЛИЧЕСТВЕНО-СТОЙНОСТНА СМЕТКА"])
    sheet.append(
        ["№ по ред", "Наименование на видовете СМР", "Ед. мярка", "Количество", "Ед. цена (лв.)", "Стойност (лв.)"]
    )
    sheet.append([1, "Кофраж за стени", "м2", 2, 195.583, 391.166])
    sheet.append([2, "Боядисване", "м2", 3, 19.5583, 58.6749])
    sheet.append([None, "ОБЩО БЕЗ ДДС", None, None, None, 449.8409])
    sheet.append([None, "ДДС 20%", None, None, None, 89.96818])
    sheet.append([None, "ВСИЧКО С ДДС", None, None, None, 539.80908])
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


@pytest.mark.asyncio
async def test_automatic_bulgarian_project_kss_calculation_and_exports(bulgarian_client: AsyncClient) -> None:
    client = bulgarian_client
    unique = uuid.uuid4().hex[:10]
    email, password = f"bulgaria-{unique}@test.io", f"Bulgaria{unique}9"
    registered = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Bulgarian workflow"},
    )
    assert registered.status_code == 201, registered.text
    from ._auth_helpers import promote_to_admin

    await promote_to_admin(email)
    logged_in = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert logged_in.status_code == 200, logged_in.text
    headers = {"Authorization": f"Bearer {logged_in.json()['access_token']}"}

    # No country, currency, locale or foreign classification selection is needed.
    created = await client.post("/api/v1/projects/", json={"name": f"Жилищна сграда {unique}"}, headers=headers)
    assert created.status_code == 201, created.text
    project = created.json()
    assert (project["country_code"], project["currency"], project["locale"]) == ("BG", "EUR", "bg")
    assert project["classification_standard"] == ""

    created_bill = await client.post(
        "/api/v1/boq/boqs/", json={"project_id": project["id"], "name": "КСС"}, headers=headers
    )
    assert created_bill.status_code == 201, created_bill.text
    bill_id = created_bill.json()["id"]
    imported = await client.post(
        f"/api/v1/boq/boqs/{bill_id}/import/auto/",
        files={"file": ("kss.xlsx", _lev_bill(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["created"] == 2

    # VAT is applied by the estimator's explicit Bulgarian template action.
    applied = await client.post(f"/api/v1/boq/boqs/{bill_id}/markups/apply-defaults/?region=BG", headers=headers)
    assert applied.status_code == 200, applied.text
    structured = await client.get(f"/api/v1/boq/boqs/{bill_id}/structured/", headers=headers)
    assert structured.status_code == 200, structured.text
    bill = structured.json()
    # 195.583 / 1.95583 = 100 EUR; 19.5583 / 1.95583 = 10 EUR.
    assert Decimal(bill["direct_cost"]) == Decimal("230")
    taxes = [row for row in bill["markups"] if row["category"] == "tax"]
    assert len(taxes) == 1
    assert Decimal(str(taxes[0]["percentage"])) == Decimal("20")
    assert Decimal(bill["grand_total"]) == Decimal("276")

    exported_pdf = await client.get(f"/api/v1/boq/boqs/{bill_id}/export/pdf", headers=headers)
    assert exported_pdf.status_code == 200, exported_pdf.text[:300]
    assert exported_pdf.headers["content-language"] == "bg"
    text = "\n".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(exported_pdf.content)).pages)
    assert "КОЛИЧЕСТВЕНО-СТОЙНОСТНА СМЕТКА" in text
    assert "Кофраж за стени" in text
    assert "Всичко с ДДС" in text
    assert "276,00" in text
    assert "46,00" in text

    exported_excel = await client.get(f"/api/v1/boq/boqs/{bill_id}/export/excel", headers=headers)
    assert exported_excel.status_code == 200, exported_excel.text[:300]
    assert exported_excel.headers["content-language"] == "bg"
    workbook = load_workbook(io.BytesIO(exported_excel.content), data_only=True)
    assert workbook.active.title == "КСС"
    rows = list(workbook.active.iter_rows(values_only=True))
    header = next(row for row in rows if row[0] == "№ по ред")
    assert header[:6] == ("№ по ред", "Наименование на СМР", "Ед. мярка", "Количество", "Ед. цена", "Стойност")
    assert "Position ID" in header
    by_description = {row[1]: row for row in rows if len(row) > 1 and row[1]}
    assert by_description["Кофраж за стени"][3:7] == (2, 100, 200, "EUR")
    assert by_description["Боядисване"][3:7] == (3, 10, 30, "EUR")
    assert by_description["Общо за СМР"][5] == 230
    assert by_description["Всичко с ДДС"][5] == 276
    assert any(isinstance(row[0], str) and row[0].startswith("Обект: Жилищна сграда") for row in rows)

    # Localized human headings still use the shared importer and stable IDs:
    # downloading and reimporting a КСС must not duplicate rows or its totals.
    reimported = await client.post(
        f"/api/v1/boq/boqs/{bill_id}/import/auto/",
        files={
            "file": (
                "kss-export.xlsx",
                exported_excel.content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        headers=headers,
    )
    assert reimported.status_code == 200, reimported.text
    assert reimported.json()["created"] == 0, reimported.json()
    after = await client.get(f"/api/v1/boq/boqs/{bill_id}/structured/", headers=headers)
    assert after.status_code == 200, after.text
    assert len(after.json()["positions"]) == 2
    assert after.json()["sections"] == []
    assert Decimal(after.json()["direct_cost"]) == Decimal("230")
    assert Decimal(after.json()["grand_total"]) == Decimal("276")
