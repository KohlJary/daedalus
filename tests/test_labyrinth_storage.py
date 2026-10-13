"""Regression tests for daedalus.labyrinth.storage.PalaceStorage.

Covers:
- GH #1: `daedalus palace status` crashed on a populated palace because
  commands.py iterated Palace.regions/buildings/rooms as if they were nested
  Region -> Building -> Room containers; Palace actually stores them as flat
  dicts keyed by slug.
- GH #2: rooms could be written to disk and then silently vanish on the next
  load() -- the "unmapped" fallback region used by _save_room created a
  directory with no region.yaml, and load() skips anything nested under a
  region whose region.yaml is missing.
"""

import logging

from daedalus.labyrinth import Building, Palace, PalaceStorage, Region, Room


def make_populated_palace(storage: PalaceStorage) -> Palace:
    """A palace with one region, one building, one room -- saved to disk."""
    palace = storage.initialize("test-project")

    region = Region(name="backend")
    storage.add_region(palace, region)

    building = Building(name="memory", region=region.slug)
    storage.add_building(palace, building)

    room = Room(name="add_message", building=building.name)
    storage.add_room(palace, room)

    return palace


def test_palace_status_counts_match_flat_dicts(tmp_path):
    storage = PalaceStorage(tmp_path)
    make_populated_palace(storage)

    reloaded = storage.load()

    # Palace.regions/buildings/rooms are flat dicts keyed by slug, not nested
    # containers -- len() on each is the correct count directly.
    assert len(reloaded.regions) == 1
    assert len(reloaded.buildings) == 1
    assert len(reloaded.rooms) == 1


def test_palace_status_command_does_not_crash_on_populated_palace(tmp_path, capsys):
    """GH #1 regression: `daedalus palace status` raised AttributeError
    ("'str' object has no attribute 'buildings'") on a populated palace."""
    from daedalus.cli.commands import palace_status

    storage = PalaceStorage(tmp_path)
    make_populated_palace(storage)

    palace_status(tmp_path)

    out = capsys.readouterr().out
    assert "Regions: 1" in out
    assert "Buildings: 1" in out
    assert "Rooms: 1" in out
    assert "Entities: 0" in out


def test_room_saved_via_add_room_is_nested_under_its_buildings_region(tmp_path):
    storage = PalaceStorage(tmp_path)
    make_populated_palace(storage)

    room_files = list((tmp_path / ".mind-palace" / "regions").glob("*/buildings/*/rooms/*.yaml"))
    assert len(room_files) == 1
    assert room_files[0].parent.parent.parent.parent.name == "backend"
    # No orphan 'unmapped' region should have been created when the building
    # was found via the in-memory Palace.
    assert not (tmp_path / ".mind-palace" / "regions" / "unmapped").exists()


def test_room_with_unknown_building_lands_in_a_loadable_unmapped_region(tmp_path):
    """
    A room whose building isn't in the palace (orphaned) falls back to an
    'unmapped' region. That region must still come back on the next load() --
    previously the fallback wrote the room's directory tree without a
    region.yaml, and load() silently skips any region directory missing one,
    so the room (and the building nested under it) vanished on reload.
    """
    storage = PalaceStorage(tmp_path)
    palace = storage.initialize("test-project")

    orphan_room = Room(name="mystery_fn", building="no-such-building")
    storage.add_room(palace, orphan_room)

    unmapped_region_yaml = tmp_path / ".mind-palace" / "regions" / "unmapped" / "region.yaml"
    assert unmapped_region_yaml.exists()

    reloaded = storage.load()

    assert "unmapped" in reloaded.regions
    assert len(reloaded.rooms) == 1
    assert len(reloaded.buildings) == 1


def test_room_file_placed_directly_under_region_is_not_silently_ignored(tmp_path, caplog):
    """
    A room YAML file placed at regions/<region>/rooms/<room>.yaml (sibling to
    buildings/, no containing building) doesn't fit the storage schema. Rather
    than silently dropping it from Palace.rooms, load() should warn clearly.
    """
    storage = PalaceStorage(tmp_path)
    palace = storage.initialize("test-project")
    region = Region(name="backend")
    storage.add_region(palace, region)

    region_dir = tmp_path / ".mind-palace" / "regions" / region.slug
    misplaced_rooms_dir = region_dir / "rooms"
    misplaced_rooms_dir.mkdir(parents=True, exist_ok=True)
    (misplaced_rooms_dir / "stray-room.yaml").write_text(
        "name: stray_room\nbuilding: ''\n", encoding="utf-8"
    )

    with caplog.at_level(logging.WARNING, logger="daedalus.labyrinth.storage"):
        reloaded = storage.load()

    assert len(reloaded.rooms) == 0
    assert any("stray-room.yaml" in record.message for record in caplog.records)
