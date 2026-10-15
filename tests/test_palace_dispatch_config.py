"""Issue #47 part 2: in-house dispatch rules from .daedalus/dispatch.json (shared) and config.json (local)."""

import json
import subprocess

import pytest
from click.testing import CliRunner

from daedalus.labyrinth import languages
from daedalus.labyrinth.query import build_query_graph

JOBS = """namespace Jobs;
public class JobQueue { public Task Publish(IJobHandler h, Message m) => null; }
public interface IJobHandler { IJobInstance CreateInstance(Message m); }
public abstract class JobInstance { public abstract Task Run(ISession s); }
public class ReportExporter(JobQueue queue) : IJobHandler
{
    public Task Export(int reportId) => queue.Publish(this, new ExportMessage(reportId));
    IJobInstance IJobHandler.CreateInstance(Message m) => new ExportInstance(m);
    private sealed class ExportInstance : JobInstance
    {
        public override Task Run(ISession s) { return Write(); }
        Task Write() => null;
    }
}
public class Unrelated(JobQueue queue) { public Task Go() => queue.Publish(null, null); }
"""
RULES = [{"publish": "JobQueue.Publish", "to": "enclosing:IJobHandler.CreateInstance"},
         {"factory": "IJobHandler.CreateInstance", "entry": "JobInstance.Run", "label": "job runner"}]


@pytest.fixture()
def repo(tmp_path):
    pytest.importorskip("tree_sitter_c_sharp")
    (tmp_path / "Jobs.cs").write_text(JOBS)
    (tmp_path / ".daedalus").mkdir()
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    languages._registry = None
    return tmp_path


def test_shared_rules_link_publish_to_factory_to_entry(repo):
    (repo / ".daedalus" / "dispatch.json").write_text(json.dumps(RULES))
    g = build_query_graph(repo).graph
    assert g.edge_labels[("Jobs.cs.ReportExporter.Export", "Jobs.cs.ReportExporter.CreateInstance")] == \
        "JobQueue.Publish (palace.dispatch)"
    assert g.edge_labels[("Jobs.cs.ReportExporter.CreateInstance", "Jobs.cs.ExportInstance.Run")] == "job runner"
    # Unrelated publishes too, but its class isn't an IJobHandler: no enclosing target
    assert not [k for k in g.edge_labels if k[0] == "Jobs.cs.Unrelated.Go"]


def test_without_rules_the_queue_is_a_dead_end(repo):
    g = build_query_graph(repo).graph
    assert "Jobs.cs.ReportExporter.CreateInstance" not in g.nodes["Jobs.cs.ReportExporter.Export"].calls


def test_local_rules_and_explicit_targets(repo):
    (repo / ".daedalus" / "config.json").write_text(json.dumps({"palace": {"dispatch": [
        {"publish": "JobQueue.Publish", "to": "IJobHandler.CreateInstance"}]}}))
    g = build_query_graph(repo).graph
    assert "Jobs.cs.ReportExporter.CreateInstance" in g.nodes["Jobs.cs.Unrelated.Go"].calls  # every implementer


def test_doctor_reports_bad_and_ignored_rules(repo):
    from daedalus import doctor
    (repo / ".daedalus" / "dispatch.json").write_text(json.dumps(RULES + [{"publish": "broken"}]))
    (repo / ".gitignore").write_text(".daedalus/*\n")
    names = [f.name for f in doctor.check_dispatch_rules(repo)]
    assert names == ["palace-dispatch-invalid", "palace-dispatch-ignored"]
    from daedalus.cli.commands import _ensure_gameplan_tracked
    _ensure_gameplan_tracked(repo)
    assert [f.name for f in doctor.check_dispatch_rules(repo)] == ["palace-dispatch-invalid"]


def test_palace_dispatch_command_lists_rules_and_edges(repo, monkeypatch):
    from daedalus.cli.main import main
    (repo / ".daedalus" / "dispatch.json").write_text(json.dumps(RULES))
    monkeypatch.chdir(repo)
    out = CliRunner().invoke(main, ["palace", "dispatch"]).output
    assert "job runner" in out and "JobQueue.Publish (palace.dispatch)" in out
    data = json.loads(CliRunner().invoke(main, ["palace", "dispatch", "--json"]).output)
    assert all(r["valid"] for r in data["rules"]) and data["edges"]["job runner"] == 1


def test_factories_link_constructed_classes_only_and_statics_dont_guess(repo):
    (repo / "More.cs").write_text(
        "namespace Jobs;\npublic class Other(JobQueue queue) : IJobHandler {\n"
        "  private Mentioned field;\n"
        "  IJobInstance IJobHandler.CreateInstance(Message m) { Mentioned f = field; return f; }\n"
        "  public static Task Fire(JobQueue q) => q.Publish(null, null);\n}\n"
        "public sealed class Mentioned : JobInstance { public override Task Run(ISession s) => null; }\n")
    (repo / ".daedalus" / "dispatch.json").write_text(json.dumps(RULES))
    languages._registry = None
    g = build_query_graph(repo).graph
    assert "More.cs.Mentioned.Run" not in g.nodes["More.cs.Other.CreateInstance"].calls  # mentioned, not built
    assert not [k for k in g.edge_labels if k[0] == "More.cs.Other.Fire"]  # static: no enclosing guess


def test_palace_dispatch_counts_edges_per_rule(repo, monkeypatch):
    from daedalus.cli.main import main
    (repo / ".daedalus" / "dispatch.json").write_text(json.dumps(RULES + [{"publish": "Typo.Publish", "to": "enclosing:IJobHandler.CreateInstance"}]))
    monkeypatch.chdir(repo)
    data = json.loads(CliRunner().invoke(main, ["palace", "dispatch", "--json"]).output)
    assert [r["edges"] for r in data["rules"]] == [1, 1, 0]
    assert "matches nothing here" in CliRunner().invoke(main, ["palace", "dispatch"]).output
