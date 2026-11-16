"""Which reading of a spreadsheet the import uses, and when the workspace AI is asked.

A file the heading rules read well is read by them, and the AI is never
asked. A file they cannot price is described by the AI as a recipe, which the
importer carries out and holds against the file's total; a recipe that does
not add up is sent back once with what is wrong. The preview's recipe comes
back with the import, so the bill imported is the bill previewed and the AI
is not asked twice.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.modules.boq import import_reading
from app.modules.boq.ai_recipe import RECIPE_PROMPT, workbook_sample
from app.modules.boq.import_reading import doubtful, read_spreadsheet, recipe_of_rules
from app.modules.boq.importers.excel import ExcelImporter
from app.modules.boq.importers.recipe import parse_recipe
from tests.unit.test_boq_import_recipe import (
    BUDGET_RECIPE,
    BUDGET_TOTAL,
    budget_form,
    running_kss,
)


class _AI:
    """The workspace AI, answering with the recipes it is given, in turn."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    async def ask(self, prompt: str) -> str:
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)


@pytest.fixture
def ai(monkeypatch: pytest.MonkeyPatch):
    def install(*answers: Any) -> _AI:
        fake = _AI(*answers)

        async def workspace_ai(_session: Any, _user: Any) -> tuple[Any, bool]:
            return fake.ask, True

        async def no_saved(*_args: Any, **_kwargs: Any) -> None:
            return None

        monkeypatch.setattr(import_reading, "workspace_ai", workspace_ai)
        monkeypatch.setattr(import_reading, "_saved_reading", no_saved)
        return fake

    return install


def _read(content: bytes, **kwargs: Any):
    options: dict[str, Any] = {
        "file_name": "file.xlsx",
        "locale": "bg",
        "overrides": None,
        "recipe": None,
        "session": object(),
        "user_id": "00000000-0000-0000-0000-000000000001",
    }
    options.update(kwargs)
    return asyncio.run(read_spreadsheet(content, **options))


def _kss() -> bytes:
    from tests.unit.test_bulgaria_kss_import import _kss as build

    return build()


def test_a_kss_the_rules_read_well_is_read_without_asking_the_ai(ai) -> None:
    fake = ai()  # any question would fail: there are no answers

    imported = _read(_kss())

    assert fake.prompts == []
    reading = imported.metadata["reading"]
    assert reading["source"] == "rules"
    assert reading["check"]["ok"] is True
    assert reading["recipe"]["sheets"][0]["columns"]["description"] == "C"


def test_a_form_the_rules_cannot_price_is_read_with_the_recipe_the_ai_writes(ai) -> None:
    fake = ai(BUDGET_RECIPE)

    imported = _read(budget_form())

    assert len(fake.prompts) == 1
    reading = imported.metadata["reading"]
    assert reading["source"] == "ai"
    assert reading["check"]["values_sum"] == BUDGET_TOTAL
    assert reading["check"]["total_matches"] is True
    assert any(w.get("code") == "layout_read_by_ai" for w in imported.warnings)


def test_a_recipe_that_does_not_add_up_is_sent_back_once_with_what_is_wrong(ai) -> None:
    short = {"sheets": [{**BUDGET_RECIPE["sheets"][0], "last_row": 11}], "currency": "BGN"}
    fake = ai(short, BUDGET_RECIPE)

    imported = _read(budget_form())

    assert len(fake.prompts) == 2
    assert "add up to" in fake.prompts[1] and "F19" in fake.prompts[1]
    assert imported.metadata["reading"]["check"]["total_matches"] is True
    assert imported.metadata["reading"]["ai_calls"] == 2


def test_an_answer_that_is_no_recipe_is_sent_back_and_the_rules_stand_when_it_stays_wrong(ai) -> None:
    fake = ai("I cannot help with that.", {"sheets": [{"sheet": "Бюджет", "first_row": 6}]})

    imported = _read(budget_form())

    assert len(fake.prompts) == 2
    assert "could not be used" in fake.prompts[1]
    assert imported.metadata["reading"]["source"] == "rules"
    assert any(w.get("code") == "ai_layout_unread" for w in imported.warnings)


def test_an_ai_that_cannot_be_reached_leaves_the_rules_reading_with_a_note(ai) -> None:
    ai(RuntimeError("provider down"))

    imported = _read(budget_form())

    assert imported.metadata["reading"]["source"] == "rules"
    assert any(w.get("code") == "ai_layout_failed" for w in imported.warnings)


def test_the_previewed_recipe_is_imported_without_asking_the_ai_again(ai) -> None:
    fake = ai()
    recipe = parse_recipe(BUDGET_RECIPE)

    imported = _read(budget_form(), recipe=recipe)
    edited = _read(budget_form(), recipe=recipe, overrides={5: ""})

    assert fake.prompts == []
    assert imported.metadata["reading"]["source"] == "preview"
    assert imported.metadata["reading"]["check"]["total_matches"] is True
    assert edited.metadata["reading"]["source"] == "person"


def test_without_a_session_the_ai_is_never_asked(ai) -> None:
    fake = ai()

    imported = _read(budget_form(), session=None)

    assert fake.prompts == []
    assert imported.metadata["reading"]["source"] == "rules"


def test_the_rules_reading_written_as_a_recipe_keeps_the_priced_row_without_a_description(ai) -> None:
    fake = ai()
    rules = asyncio.run(ExcelImporter.parse(running_kss()))
    rules_sum = sum(p.quantity * p.unit_rate for p in rules.positions if not p.is_section)

    imported = _read(running_kss())
    check = imported.metadata["reading"]["check"]

    assert fake.prompts == []
    assert recipe_of_rules(rules) is not None
    assert imported.metadata["reading"]["source"] == "rules"
    assert check["total_matches"] is True and check["file_total_cell"] == "J12"
    assert round(check["imported_sum"] - rules_sum, 2) == 1176.0


def test_a_reading_with_inferred_columns_or_no_prices_read_is_doubtful() -> None:
    form = asyncio.run(ExcelImporter.parse(budget_form()))
    kss = asyncio.run(ExcelImporter.parse(_kss()))

    assert doubtful(form)
    assert not doubtful(kss)


def test_the_ai_is_shown_a_fenced_sample_of_the_sheet_with_lettered_columns() -> None:
    sample = workbook_sample(budget_form())
    prompt = RECIPE_PROMPT.format(filename="f.xlsx", sample=sample)

    assert '== Sheet "Бюджет"' in sample
    assert "r5: B=Етап на изграждането; C=мярка; D=количество; E=ед.цена; F=стойност, лв" in sample
    assert "r19: B=ОБЩО ЗА ОБЕКТА, лв без ДДС" in sample
    assert prompt.index("<<<UNTRUSTED_USER_CONTENT") < prompt.index("Етап на изграждането")
    assert prompt.index("Етап на изграждането") < prompt.index("UNTRUSTED_USER_CONTENT>>>")


def test_a_long_sheet_is_sampled_at_its_head_middle_and_tail() -> None:
    from tests.unit.test_boq_import_recipe import _book

    rows = [["№", "Описание", "мярка", "к-во"]] + [[i, f"Ред {i}", "м2", i] for i in range(1, 2001)]
    sample = workbook_sample(_book({"Дълга": rows}))

    assert "r2: A=1; B=Ред 1" in sample
    assert "r2001: A=2000; B=Ред 2000" in sample
    assert "…" in sample
    assert sample.count("\n") < 100
