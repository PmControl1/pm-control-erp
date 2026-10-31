#!/usr/bin/env python3
"""Build the Bulgaria pack's vocabulary overlay from the interface's Bulgarian locale.

    python packs/bulgaria-bg/tools/build_vocabulary.py          # write the overlay
    python packs/bulgaria-bg/tools/build_vocabulary.py --check  # fail if it is stale

The Bulgarian interface names a priced bill of quantities four ways: the
English loan word "BOQ", "КСС", "количествена сметка" and, rarely,
"количествено-стойностна сметка". On one screen the editor is a "BOQ", the
sidebar says "Количествена сметка" and the export says "КСС". A Bulgarian
estimator has one name for the thing they price: the КСС, written out as
количествено-стойностна сметка. ("Количествена сметка" on its own is the
designer's unpriced bill, which is not what the editor holds.)

The pack fixes the vocabulary as an overlay, ``locales/bg.json``, which the
frontend merges over the shipped Bulgarian strings while the pack is active
(``partnerPackVocabulary.ts``). The overlay is generated rather than written
by hand so it can be rebuilt after an upstream merge changes the locale; the
rules are below and ``--check`` is what a test runs.

Rules, in order:

1. Module names first: "Бърза количествена сметка (ИИ)" becomes
   "Бърза КСС (ИИ)", and "Търгуване" (which means trading, as in shares)
   becomes "Търгове".
2. "количествена сметка" in each of its forms becomes the same form of
   "количествено-стойностна сметка". The noun and its gender do not change,
   so nothing around it has to.
3. The loan word "BOQ"/"BoQ"/"BOQs" becomes "КСС" where it is prose: not part
   of an identifier, a route or an i18next variable, and not in the name of a
   country exchange module, where it is that format's own name.
4. "BOQ позиция" and its forms, an English noun-adjunct compound, become
   "позиция от КСС".
5. The locale treated the loan word as masculine about as often as feminine.
   КСС stands for "сметка" and is feminine, as the locale's own КСС sentences
   already treat it, so a determiner or adjective agreeing with it as the
   head noun takes the feminine form ("този BOQ" -> "тази КСС"). Where КСС
   modifies the next noun ("всеки BOQ пакет") the agreement belongs to that
   noun and is left alone.
6. A handful of labels are set by hand (``MANUAL``).

An entry goes in the overlay only when the rules change it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parents[1]
REPO = PACK.parents[1]
LOCALE_TS = REPO / "frontend" / "src" / "app" / "locales" / "bg.ts"
OVERLAY = PACK / "src" / "openconstructionerp_bulgaria_bg" / "locales" / "bg.json"

#: ``  "key": "value",`` - the shape of every line in a locale file.
PAIR = re.compile(r'^\s*"((?:[^"\\]|\\.)*)"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,?\s*$')

#: Labels set by hand. Short sidebar and legend labels read better with the
#: abbreviation, and the request-for-information module has a Bulgarian name.
MANUAL: dict[str, str] = {
    "nav.boq": "КСС",
    "nav.boq_templates": "Шаблони на КСС",
    "bim.legend_boq_coverage": "Покритие с КСС",
    "nav.rfi": "Запитвания (RFI)",
    "guide.tendering.intro": None,  # rebuilt below from the rule output
}

MODULE_NAMES: list[tuple[str, str]] = [
    ("Бърза количествена сметка (ИИ)", "Бърза КСС (ИИ)"),
    ("Търгуване", "Търгове"),
]

INFLECT: dict[str, str] = {
    "количествена сметка": "количествено-стойностна сметка",
    "количествената сметка": "количествено-стойностната сметка",
    "количествени сметки": "количествено-стойностни сметки",
    "количествените сметки": "количествено-стойностните сметки",
}


def _capitalised(text: str) -> str:
    return text[:1].upper() + text[1:]


_INFLECT_ALL = {**INFLECT, **{_capitalised(k): _capitalised(v) for k, v in INFLECT.items()}}
_INFLECT_RE = re.compile(
    r"(?<![а-яА-Я-])(" + "|".join(re.escape(k) for k in sorted(_INFLECT_ALL, key=len, reverse=True)) + r")(?![а-яА-Я])"
)

_LOAN_WORD = re.compile(r"(?<![\w/{.\-])(?:BOQs|BOQ|BoQ)(?![\w/}])")
_EXCHANGE_KEY = re.compile(r"^nav\.[a-z]+_boq_exchange$")
_ADJUNCT = re.compile(r"\bКСС (позиция|позицията|позиции|позициите|ред|реда|редове|редовете)\b")

AGREE: dict[str, str] = {
    "този": "тази",
    "това": "тази",
    "вашия": "вашата",
    "вашият": "вашата",
    "вашето": "вашата",
    "неговия": "неговата",
    "неговият": "неговата",
    "моя": "моята",
    "мой": "моя",
    "твоя": "твоята",
    "остойностен": "остойностена",
    "остойностено": "остойностена",
    "остойностения": "остойностената",
    "остойностеното": "остойностената",
    "остойностеният": "остойностената",
    "пълен": "пълна",
    "пълния": "пълната",
    "проектен": "проектна",
    "проектния": "проектната",
    "друг": "друга",
    "другия": "другата",
    "свързан": "свързана",
    "свързано": "свързана",
    "свързания": "свързаната",
    "свързаното": "свързаната",
    "структуриран": "структурирана",
    "избран": "избрана",
    "избрания": "избраната",
    "избраният": "избраната",
    "реален": "реална",
    "реалния": "реалната",
    "целеви": "целева",
    "целевия": "целевата",
    "всеки": "всяка",
    "нов": "нова",
    "новия": "новата",
    "новият": "новата",
    "празен": "празна",
    "празния": "празната",
    "съществуващия": "съществуващата",
    "заключен": "заключена",
    "заключения": "заключената",
    "един": "една",
    "основен": "основна",
    "основния": "основната",
    "изходен": "изходна",
    "изходния": "изходната",
    "активен": "активна",
    "активния": "активната",
    "текущия": "текущата",
    "текущият": "текущата",
    "цял": "цяла",
    "целия": "цялата",
    "последния": "последната",
    "първия": "първата",
    "импортиран": "импортирана",
    "импортирания": "импортираната",
}
_FUNCTION_WORDS = (
    "и|или|е|са|с|със|в|във|на|за|от|не|ще|след|като|преди|чрез|спрямо|към|по|до|при|без|"
    "може|трябва|вече|все|още|се|го|ги|ѝ|й|им|няма|има|който|която|което|които|така|"
    "носи|държи|съдържа|остава|става|бъде|беше|бе"
)
_AGREE_RE = re.compile(
    r"(?<![а-яА-Я])(" + "|".join(sorted(AGREE, key=len, reverse=True)) + r")(\s+)"
    r"(?=КСС(?:$|[^\w\s-]|\s+(?:" + _FUNCTION_WORDS + r")\b|\s*$))",
    re.IGNORECASE,
)


def _feminine(match: re.Match[str]) -> str:
    word = match.group(1)
    fem = AGREE[word.lower()]
    return (_capitalised(fem) if word[0].isupper() else fem) + match.group(2)


def fixed(key: str, value: str) -> str:
    """The value with the bill named the one way the trade names it."""
    if _EXCHANGE_KEY.match(key):
        return value
    out = value
    for old, new in MODULE_NAMES:
        out = out.replace(old, new)
    out = _INFLECT_RE.sub(lambda m: _INFLECT_ALL[m.group(1)], out)
    out = _LOAN_WORD.sub("КСС", out)
    out = _ADJUNCT.sub(r"\1 от КСС", out)
    out = _AGREE_RE.sub(_feminine, out)
    out = re.sub(r"КСС, (който|което)\b", "КСС, която", out)
    out = out.replace("КСС (КСС)", "КСС")
    if value[:1].isupper() and out[:1].islower():
        out = _capitalised(out)
    if key == "guide.tendering.intro" and out.startswith("Търгове изпраща"):
        out = "Модулът „Търгове“ изпраща" + out[len("Търгове изпраща") :]
    return out


def read_locale(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = PAIR.match(line)
        if match:
            entries[match.group(1)] = json.loads(f'"{match.group(2)}"')
    return entries


def build(locale: dict[str, str]) -> dict[str, object]:
    translation: dict[str, str] = {}
    for key in sorted(locale):
        value = locale[key]
        manual = MANUAL.get(key)
        new = manual if manual is not None else fixed(key, value)
        if new != value:
            translation[key] = new
    return {
        "_meta": {
            "locale": "bg",
            "name": "Български (строителна терминология)",
            "fallback": "bg",
            "coverage": "partial",
            "generated_by": "packs/bulgaria-bg/tools/build_vocabulary.py",
            "notes": (
                "Количествено-стойностната сметка се нарича навсякъде КСС или количествено-стойностна "
                "сметка, вместо BOQ и количествена сметка; Търгове вместо Търгуване."
            ),
        },
        "translation": translation,
    }


def render(overlay: dict[str, object]) -> str:
    return json.dumps(overlay, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when the overlay is out of date")
    args = parser.parse_args()
    text = render(build(read_locale(LOCALE_TS)))
    if args.check:
        current = OVERLAY.read_text(encoding="utf-8") if OVERLAY.exists() else ""
        if current != text:
            print(f"{OVERLAY} is out of date; run {Path(__file__).name} to rebuild it.", file=sys.stderr)
            return 1
        return 0
    OVERLAY.parent.mkdir(parents=True, exist_ok=True)
    OVERLAY.write_text(text, encoding="utf-8")
    print(f"wrote {len(json.loads(text)['translation'])} entries to {OVERLAY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
