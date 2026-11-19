"""An uploaded file keeps the name it was uploaded with.

The name people see used to be the name made safe for disk, so every space
and punctuation mark became "_" in every list, and a long Cyrillic name (legal
on Windows, more bytes than Linux allows) failed with "Failed to save file to
disk". The shown name and the disk name are now separate.
"""

from __future__ import annotations

import pytest

from app.modules.documents.service import (
    _blocked_extension_segment,
    _disk_filename,
    _display_filename,
)

# Invented names, as a Bulgarian office would type them.
KEPT = [
    "Бележки от оглед.txt",
    "Чертеж № 5 – Фасада (окончателен) v2.pdf",
    "100%_план#1 & ревизия;'final'.pdf",
    "план 🏗️ етаж 2.pdf",
    "Протокол без разширение",
    "ПЛАН_ЕТАЖ.PDF",
]


@pytest.mark.parametrize("name", KEPT)
def test_the_shown_name_is_the_uploaded_name(name: str) -> None:
    assert _display_filename(name) == name


@pytest.mark.parametrize(
    ("uploaded", "shown"),
    [
        ("/etc/passwd", "passwd"),
        ("../../boot.ini", "boot.ini"),
        ("C:\\Users\\inspector\\Desktop\\Протокол 3.pdf", "Протокол 3.pdf"),
        ("  отстъп отпред.pdf  ", "отстъп отпред.pdf"),
        ("ред\nнов.pdf", "реднов.pdf"),
        ("", "untitled"),
        ("...", "untitled"),
    ],
)
def test_a_path_and_control_characters_are_dropped(uploaded: str, shown: str) -> None:
    assert _display_filename(uploaded) == shown


def test_a_right_to_left_override_cannot_disguise_an_executable() -> None:
    # Shown as "invoiceexe.pdf" with the override; without it, it is an .exe.
    shown = _display_filename("invoice\u202efdp.exe")
    assert "\u202e" not in shown
    assert _blocked_extension_segment(shown) == ".exe"


def test_a_200_character_cyrillic_name_fits_on_disk_and_keeps_its_extension() -> None:
    name = ("Многостранична_техническа_документация_" * 6)[:200] + ".pdf"
    shown = _display_filename(name)
    assert shown == name
    on_disk = _disk_filename(shown)
    assert len(on_disk.encode()) <= 150
    assert on_disk.endswith(".pdf")


def test_a_name_longer_than_the_column_is_cut_before_its_extension() -> None:
    shown = _display_filename("ж" * 400 + ".dwg")
    assert len(shown) == 255
    assert shown.endswith(".dwg")


@pytest.mark.parametrize("name", KEPT)
def test_the_disk_name_has_only_safe_characters(name: str) -> None:
    on_disk = _disk_filename(_display_filename(name))
    assert " " not in on_disk and "/" not in on_disk and "#" not in on_disk
