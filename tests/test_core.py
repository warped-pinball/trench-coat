import base64
import json
import struct

import pytest

import src.core as core
from src.core import (
    DEFAULT_SYSTEM,
    SYSTEM_LABEL,
    SYSTEM_UPDATE_ASSET,
    FirmwarePlanError,
    FirmwareSelection,
    choose_batch_firmware,
    custom_flash_concerns,
    custom_image_systems,
    find_system_images,
    firmware_system,
    flash_firmware,
    get_files_from_update_file,
    list_bundled_uf2,
    read_drive_info,
    read_drive_processor,
    system_for_boards,
    uf2_target_processor,
)

UF2_MAGIC_START0 = 0x0A324655  # "UF2\n"
UF2_MAGIC_START1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30
UF2_FLAG_FAMILY_ID_PRESENT = 0x00002000

RP2040_FAMILY = 0xE48BFF56
ABSOLUTE_FAMILY = 0xE48BFF57
RP2350_ARM_S_FAMILY = 0xE48BFF59


def make_uf2_block(family_id=None):
    """Build one valid 512-byte UF2 block."""
    flags = UF2_FLAG_FAMILY_ID_PRESENT if family_id is not None else 0
    header = struct.pack(
        "<8I",
        UF2_MAGIC_START0,
        UF2_MAGIC_START1,
        flags,
        0x10000000,  # target address
        256,  # payload size
        0,  # block number
        1,  # total blocks
        family_id or 0,
    )
    payload = b"\x00" * 476
    footer = struct.pack("<I", UF2_MAGIC_END)
    block = header + payload + footer
    assert len(block) == 512
    return block


def write_uf2(tmp_path, name, families):
    path = tmp_path / name
    path.write_bytes(b"".join(make_uf2_block(f) for f in families))
    return str(path)


class TestUf2TargetProcessor:
    def test_rp2040(self, tmp_path):
        path = write_uf2(tmp_path, "fw.uf2", [RP2040_FAMILY])
        assert uf2_target_processor(path) == "rp2040"

    def test_rp2350(self, tmp_path):
        path = write_uf2(tmp_path, "fw.uf2", [RP2350_ARM_S_FAMILY])
        assert uf2_target_processor(path) == "rp2350"

    def test_rp2350_with_stray_absolute_block(self, tmp_path):
        # Real RP2350 images carry a metadata block with the absolute family.
        path = write_uf2(tmp_path, "fw.uf2", [RP2350_ARM_S_FAMILY, ABSOLUTE_FAMILY])
        assert uf2_target_processor(path) == "rp2350"

    def test_universal_nuke(self, tmp_path):
        # A universal flash-nuke is RP2040 + absolute blocks.
        path = write_uf2(tmp_path, "nuke.uf2", [RP2040_FAMILY, ABSOLUTE_FAMILY])
        assert uf2_target_processor(path) == "universal"

    def test_unknown_family(self, tmp_path):
        path = write_uf2(tmp_path, "fw.uf2", [0x12345678])
        assert uf2_target_processor(path) is None

    def test_no_family_flag(self, tmp_path):
        path = write_uf2(tmp_path, "fw.uf2", [None])
        assert uf2_target_processor(path) is None

    def test_missing_file(self, tmp_path):
        assert uf2_target_processor(str(tmp_path / "nope.uf2")) is None

    def test_truncated_file(self, tmp_path):
        path = tmp_path / "short.uf2"
        path.write_bytes(b"UF2\n" + b"\x00" * 10)
        assert uf2_target_processor(str(path)) is None

    def test_non_uf2_garbage(self, tmp_path):
        path = tmp_path / "garbage.uf2"
        path.write_bytes(b"\xff" * 1024)
        assert uf2_target_processor(str(path)) is None


class TestFirmwareSystem:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("Vector_WPC_v5.uf2", "wpc"),
            ("Vector_WPC_v6.uf2", "wpc"),
            ("Vector_DataEast_v1.uf2", "data_east"),
            ("vector_data_east_v2.uf2", "data_east"),
            ("vector-data-east.uf2", "data_east"),
            ("Vector_Classics_V1.uf2", "classic"),
            ("vector_system_11_and_9_v4.uf2", "sys11"),
            ("something_else.uf2", DEFAULT_SYSTEM),
            ("", DEFAULT_SYSTEM),
            (None, DEFAULT_SYSTEM),
        ],
    )
    def test_keyword_mapping(self, filename, expected):
        assert firmware_system(filename) == expected

    def test_system_keyword_does_not_match_em(self):
        # "em" is a substring of "system"; the sys11 image must not map to EM.
        assert firmware_system("vector_system_11_and_9_v4.uf2") != "em"


class TestFindSystemImages:
    BUNDLED = [
        "/app/uf2/Vector_WPC_v5.uf2",
        "/app/uf2/Vector_DataEast_v1.uf2",
        "/app/uf2/vector_system_11_and_9_v4.uf2",
        "/app/uf2/Vector_Classics_V1.uf2",
    ]

    def test_sys11_has_an_image_per_board(self):
        images = find_system_images("sys11", self.BUNDLED)
        assert images["rp2040"].endswith("vector_system_11_and_9_v4.uf2")
        assert images["rp2350"].endswith("Vector_DataEast_v1.uf2")

    def test_each_bundled_system(self):
        assert find_system_images("wpc", self.BUNDLED) == {"rp2350": "/app/uf2/Vector_WPC_v5.uf2"}
        assert find_system_images("data_east", self.BUNDLED) == {"rp2350": "/app/uf2/Vector_DataEast_v1.uf2"}
        assert find_system_images("classic", self.BUNDLED) == {"rp2350": "/app/uf2/Vector_Classics_V1.uf2"}

    def test_em_shares_wpc_os(self):
        assert find_system_images("em", self.BUNDLED) == {"rp2350": "/app/uf2/Vector_WPC_v5.uf2"}

    def test_unreleased_system(self):
        assert find_system_images("whitestar", self.BUNDLED) == {}

    def test_unknown_system(self):
        assert find_system_images("not_a_system", self.BUNDLED) == {}

    def test_sys11_with_only_pico_w_image(self):
        assert find_system_images("sys11", ["/app/uf2/vector_system_11_and_9_v4.uf2"]) == {"rp2040": "/app/uf2/vector_system_11_and_9_v4.uf2"}

    def test_skips_image_built_for_the_other_chip(self, tmp_path):
        # A filename collision must never put an RP2350 image on a Pico W.
        wrong = write_uf2(tmp_path, "a_system_rp2350.uf2", [RP2350_ARM_S_FAMILY])
        right = write_uf2(tmp_path, "b_system_rp2040.uf2", [RP2040_FAMILY])
        assert find_system_images("sys11", [wrong, right])["rp2040"] == right

    def test_real_bundled_sys11_images_target_the_right_chip(self):
        images = find_system_images("sys11", list_bundled_uf2())
        assert uf2_target_processor(images["rp2040"]) == "rp2040"
        assert uf2_target_processor(images["rp2350"]) == "rp2350"


def write_info(tmp_path, name, text):
    drive = tmp_path / name
    drive.mkdir()
    (drive / "INFO_UF2.TXT").write_text(text)
    return str(drive)


PICO_W_INFO = "UF2 Bootloader v3.0\nModel: Raspberry Pi RP2\nBoard-ID: RPI-RP2\n"
PICO_2W_INFO = "UF2 Bootloader v1.0\nModel: Raspberry Pi RP2350\nBoard-ID: RP2350\n"


class TestReadDriveInfo:
    def test_pico_w(self, tmp_path):
        info = read_drive_info(write_info(tmp_path, "d", PICO_W_INFO))
        assert info == {"processor": "rp2040", "board_id": "RPI-RP2", "model": "Raspberry Pi RP2", "bootloader": "UF2 Bootloader v3.0"}

    def test_pico_2w(self, tmp_path):
        info = read_drive_info(write_info(tmp_path, "d", PICO_2W_INFO))
        assert info["processor"] == "rp2350"
        assert info["board_id"] == "RP2350"

    def test_unknown_board(self, tmp_path):
        assert read_drive_info(write_info(tmp_path, "d", "Board-ID: SOMETHING\n"))["processor"] is None

    def test_missing_file(self, tmp_path):
        assert read_drive_info(str(tmp_path))["processor"] is None


def drives(*processors):
    return {f"{chr(69 + i)}:\\": {"processor": p, "board_id": None, "model": None, "bootloader": None} for i, p in enumerate(processors)}


class TestChooseBatchFirmware:
    SYS11 = FirmwareSelection("sys11", {"rp2040": "sys11_v4.uf2", "rp2350": "dataeast.uf2"})
    WPC = FirmwareSelection("wpc", {"rp2350": "wpc.uf2"})

    def test_pico_w_batch_gets_legacy_image(self):
        assert choose_batch_firmware(self.SYS11, drives("rp2040", "rp2040")) == ("sys11_v4.uf2", "rp2040")

    def test_pico_2w_batch_gets_dataeast_image(self):
        assert choose_batch_firmware(self.SYS11, drives("rp2350")) == ("dataeast.uf2", "rp2350")

    def test_mixed_batch_rejected(self):
        with pytest.raises(FirmwarePlanError, match="Mixed board types"):
            choose_batch_firmware(self.SYS11, drives("rp2040", "rp2350"))

    def test_series_without_image_for_chip_rejected(self):
        with pytest.raises(FirmwarePlanError, match="No WPC OS"):
            choose_batch_firmware(self.WPC, drives("rp2040"))

    def test_unreadable_drive_rejected_for_bundled_series(self):
        with pytest.raises(FirmwarePlanError, match="Could not tell"):
            choose_batch_firmware(self.SYS11, drives(None))

    def test_custom_image_flashes_as_requested(self):
        custom = FirmwareSelection("sys11", {"rp2350": "mine.uf2"}, custom=True)
        assert choose_batch_firmware(custom, drives("rp2040"))[0] == "mine.uf2"
        assert choose_batch_firmware(custom, drives(None))[0] == "mine.uf2"

    def test_custom_image_refuses_a_part_identified_batch(self):
        # The post-wipe re-check would reject the unreadable drive after every
        # board had been erased, so it has to be refused up front.
        custom = FirmwareSelection("sys11", {"rp2350": "mine.uf2"}, custom=True)
        with pytest.raises(FirmwarePlanError, match="Could not tell"):
            choose_batch_firmware(custom, drives("rp2350", None))


class TestCustomFlashConcerns:
    def custom(self, tmp_path, families):
        path = write_uf2(tmp_path, "mine.uf2", families)
        return FirmwareSelection.from_custom(path), path

    def test_bundled_series_has_none(self):
        sel = FirmwareSelection("wpc", {"rp2350": "wpc.uf2"})
        assert custom_flash_concerns(sel, "wpc.uf2", "rp2350") == []

    def test_matching_custom_image_has_none(self, tmp_path):
        sel, path = self.custom(tmp_path, [RP2350_ARM_S_FAMILY])
        assert custom_flash_concerns(sel, path, "rp2350") == []

    def test_universal_image_on_known_board_has_none(self, tmp_path):
        sel, path = self.custom(tmp_path, [RP2040_FAMILY, ABSOLUTE_FAMILY])
        assert custom_flash_concerns(sel, path, "rp2040") == []

    def test_chip_mismatch(self, tmp_path):
        sel, path = self.custom(tmp_path, [RP2350_ARM_S_FAMILY])
        (concern,) = custom_flash_concerns(sel, path, "rp2040")
        assert "built for Pico 2 W" in concern and "Pico W (RP2040)" in concern

    def test_unidentified_board(self, tmp_path):
        sel, path = self.custom(tmp_path, [RP2350_ARM_S_FAMILY])
        (concern,) = custom_flash_concerns(sel, path, None)
        assert "Could not tell" in concern

    def test_image_with_no_family_id(self, tmp_path):
        sel, path = self.custom(tmp_path, [])
        (concern,) = custom_flash_concerns(sel, path, "rp2040")
        assert "does not say which chip" in concern


class Aborted(Exception):
    pass


class TestFlashFirmwareConfirmation:
    """A board already in bootloader mode skips the running-board prompt, so
    flash_firmware has to ask before it erases anything."""

    @pytest.fixture
    def bench(self, tmp_path, monkeypatch):
        drive = write_info(tmp_path, "drive", PICO_W_INFO)
        copies = []

        def abort(*a, **k):
            raise Aborted()

        monkeypatch.setattr(core, "get_all_boards_into_bootloader", lambda: None)
        monkeypatch.setattr(core, "list_rpi_rp2_drives", lambda: [drive])
        monkeypatch.setattr(core, "graceful_exit", abort)
        monkeypatch.setattr(core.time, "sleep", abort)  # first thing after the checks
        monkeypatch.setattr(core.shutil, "copy", lambda *a: copies.append(a))
        return copies

    def mismatched(self, tmp_path):
        return FirmwareSelection.from_custom(write_uf2(tmp_path, "mine.uf2", [RP2350_ARM_S_FAMILY]))

    def test_declined_mismatch_erases_nothing(self, tmp_path, bench):
        asked = []
        with pytest.raises(Aborted):
            flash_firmware(self.mismatched(tmp_path), confirm=lambda: asked.append(1) or False)
        assert asked == [1] and bench == []

    def test_no_way_to_ask_erases_nothing(self, tmp_path, bench, monkeypatch):
        monkeypatch.setattr(core.time, "sleep", lambda s: pytest.fail("reached the wipe"))
        with pytest.raises(Aborted):
            flash_firmware(self.mismatched(tmp_path))
        assert bench == []

    def test_accepted_mismatch_goes_ahead(self, tmp_path, bench):
        with pytest.raises(Aborted):  # the stubbed sleep, i.e. past the checks
            flash_firmware(self.mismatched(tmp_path), confirm=lambda: True)

    def test_mismatch_accepted_earlier_is_not_asked_again(self, tmp_path, bench):
        selection = self.mismatched(tmp_path)
        selection.accepted_mismatches = {"rp2040"}
        with pytest.raises(Aborted):
            flash_firmware(selection, confirm=lambda: pytest.fail("asked twice"))

    def test_unknown_image_is_asked_even_after_an_earlier_yes(self, tmp_path, bench):
        selection = FirmwareSelection.from_custom(write_uf2(tmp_path, "mine.uf2", []))
        selection.accepted_mismatches = {"rp2040"}
        asked = []
        with pytest.raises(Aborted):
            flash_firmware(selection, confirm=lambda: asked.append(1) or False)
        assert asked == [1] and bench == []


class TestReadDriveProcessor:
    def test_retries_until_the_drive_answers(self, tmp_path, monkeypatch):
        answers = iter([None, None, "rp2350"])
        monkeypatch.setattr(core, "read_drive_info", lambda d: {"processor": next(answers)})
        monkeypatch.setattr(core.time, "sleep", lambda s: None)
        assert read_drive_processor("E:") == "rp2350"

    def test_gives_up_at_the_deadline(self, monkeypatch):
        clock = iter([0, 1, 100])
        monkeypatch.setattr(core, "read_drive_info", lambda d: {"processor": None})
        monkeypatch.setattr(core.time, "sleep", lambda s: None)
        monkeypatch.setattr(core.time, "monotonic", lambda: next(clock))
        assert read_drive_processor("E:", timeout=15) is None


class TestCustomImageSystems:
    def test_data_east_image_is_shared_with_sys11(self):
        assert custom_image_systems("/x/Vector_DataEast_v1.uf2") == ["sys11", "data_east"]

    def test_wpc_image_is_shared_with_em(self):
        assert custom_image_systems("Vector_WPC_v5.uf2") == ["wpc", "em"]

    def test_unshared_images(self):
        assert custom_image_systems("vector_system_11_and_9_v4.uf2") == ["sys11"]
        assert custom_image_systems("Vector_Classics_V1.uf2") == ["classic"]

    def test_unrecognised_name(self):
        assert custom_image_systems("mine.uf2") == []


class TestFirmwareSelectionFromCustom:
    def test_named_series_wins_over_the_filename(self, tmp_path):
        path = write_uf2(tmp_path, "Vector_DataEast_v1.uf2", [RP2350_ARM_S_FAMILY])
        assert FirmwareSelection.from_custom(path).system == "data_east"
        assert FirmwareSelection.from_custom(path, "sys11").system == "sys11"

    def test_targets_its_own_chip(self, tmp_path):
        path = write_uf2(tmp_path, "mine.uf2", [RP2040_FAMILY])
        sel = FirmwareSelection.from_custom(path)
        assert sel.custom and sel.images == {"rp2040": path}

    def test_universal_image_targets_both(self, tmp_path):
        path = write_uf2(tmp_path, "mine.uf2", [RP2040_FAMILY, ABSOLUTE_FAMILY])
        assert set(FirmwareSelection.from_custom(path).images) == {"rp2040", "rp2350"}


class TestSystemForBoards:
    def test_rp2040_is_sys11(self):
        assert system_for_boards([{"processor": "rp2040", "system": None}]) == "sys11"

    def test_rp2350_reports_its_system(self):
        assert system_for_boards([{"processor": "rp2350", "system": "wpc"}]) == "wpc"

    def test_no_boards_uses_default(self):
        assert system_for_boards([]) == DEFAULT_SYSTEM
        assert system_for_boards([], default="wpc") == "wpc"

    def test_undetected_board_uses_default(self):
        assert system_for_boards([{"processor": None, "system": None}]) == DEFAULT_SYSTEM


class TestSystemTables:
    def test_every_system_has_update_asset_and_label(self):
        assert set(SYSTEM_UPDATE_ASSET) == set(SYSTEM_LABEL)

    def test_bundled_uf2s_found_in_dev_checkout(self):
        names = [p.split("/")[-1] for p in list_bundled_uf2()]
        assert "nuke.uf2" in names
        assert any("wpc" in n.lower() for n in names)


def make_update_file(tmp_path, files, metadata=None):
    """Build an update file in the vector 1.0 format:
    line 1 metadata JSON, then filename{json-metadata}base64 lines,
    then a signature line (no filename)."""
    lines = [json.dumps(metadata or {"update_file_format": "1.0"})]
    for filename, contents, file_meta in files:
        b64 = base64.b64encode(contents).decode()
        lines.append(f"{filename}{json.dumps(file_meta)}{b64}")
    lines.append(json.dumps({"sha256": "00", "signature": "AA=="}))
    path = tmp_path / "update.json"
    path.write_text("\n".join(lines) + "\n")
    return str(path)


class TestGetFilesFromUpdateFile:
    def test_parses_files(self, tmp_path):
        path = make_update_file(
            tmp_path,
            [
                ("main.py", b"print('hi')", {}),
                ("lib/util.py", b"x = 1", {"execute": True}),
            ],
        )
        files = get_files_from_update_file(path)
        assert len(files) == 2
        assert files[0]["filename"] == "main.py"
        assert base64.b64decode(files[0]["base64_contents"]) == b"print('hi')"
        assert files[1]["metadata"] == {"execute": True}

    def test_skips_signature_and_blank_lines(self, tmp_path):
        path = make_update_file(tmp_path, [("a.py", b"a", {})])
        # add blank lines
        with open(path, "a") as f:
            f.write("\n\n")
        files = get_files_from_update_file(path)
        assert [f["filename"] for f in files] == ["a.py"]
