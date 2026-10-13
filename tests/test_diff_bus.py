"""Tests for daedalus.ariadne.diff_bus: Diff.from_git_diff parsing and AriadneBus round-trips.

This is the lowest-level piece of Ariadne's parallel-worker orchestration and had zero test
coverage; these tests establish a baseline so future changes don't silently break diff parsing
or the pending/verified/rejected directory bookkeeping.
"""

from daedalus.ariadne.diff_bus import AriadneBus, Diff, DiffStatus


SAMPLE_DIFF = """\
diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -10,3 +10,4 @@ def handler():
     do_a()
     do_b()
+    do_c()
diff --git a/src/new_module.py b/src/new_module.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/src/new_module.py
@@ -0,0 +1,2 @@
+def new_fn():
+    pass
diff --git a/src/old_module.py b/src/old_module.py
deleted file mode 100644
index 4444444..0000000
--- a/src/old_module.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def old_fn():
-    pass
"""


def test_from_git_diff_classifies_files_by_change_type():
    diff = Diff.from_git_diff("wp-1", "icarus-1", SAMPLE_DIFF, "Add do_c, a new module, remove an old one")

    assert diff.files_modified == ["src/app.py"]
    assert diff.files_added == ["src/new_module.py"]
    assert diff.files_deleted == ["src/old_module.py"]
    assert diff.all_affected_files() == {"src/app.py", "src/new_module.py", "src/old_module.py"}


def test_from_git_diff_is_deterministic_id():
    diff_a = Diff.from_git_diff("wp-1", "icarus-1", SAMPLE_DIFF, "desc")
    diff_b = Diff.from_git_diff("wp-2", "icarus-2", SAMPLE_DIFF, "different desc")

    # Same content -> same id, regardless of work/instance/description
    assert diff_a.id == diff_b.id
    assert diff_a.status == DiffStatus.PENDING


def test_from_git_diff_extracts_line_changes_for_modified_file():
    diff = Diff.from_git_diff("wp-1", "icarus-1", SAMPLE_DIFF, "desc")

    assert "src/app.py" in diff.line_changes
    start, end, change_type = diff.line_changes["src/app.py"][0]
    assert change_type == "modify"
    assert start == 10


def test_bus_submit_and_list_pending_round_trip(tmp_path):
    bus = AriadneBus(root=tmp_path / "bus")
    bus.initialize()
    assert bus.is_initialized()

    diff = Diff.from_git_diff("wp-1", "icarus-1", SAMPLE_DIFF, "desc")
    diff_id = bus.submit_diff(diff)

    assert diff_id == diff.id
    pending = bus.list_pending_diffs()
    assert [d.id for d in pending] == [diff.id]
    assert pending[0].status == DiffStatus.PENDING


def test_bus_update_status_moves_diff_between_directories(tmp_path):
    bus = AriadneBus(root=tmp_path / "bus")
    bus.initialize()

    diff = Diff.from_git_diff("wp-1", "icarus-1", SAMPLE_DIFF, "desc")
    bus.submit_diff(diff)

    assert bus.update_diff_status(diff.id, DiffStatus.VERIFIED)

    assert bus.list_pending_diffs() == []
    verified = bus.list_verified_diffs()
    assert len(verified) == 1
    assert verified[0].status == DiffStatus.VERIFIED
    assert verified[0].verified_at is not None


def test_bus_get_diff_returns_none_for_unknown_id(tmp_path):
    bus = AriadneBus(root=tmp_path / "bus")
    bus.initialize()

    assert bus.get_diff("does-not-exist") is None
