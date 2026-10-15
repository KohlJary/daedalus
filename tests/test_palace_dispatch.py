"""Issue #47: edges across framework dispatch (message buses, Hangfire, Celery), labelled in the output."""

import json
import subprocess

import pytest
from click.testing import CliRunner

from daedalus.labyrinth import languages
from daedalus.labyrinth.query import build_query_graph

CS = """namespace Shop;
public record ShipOrder(int OrderId) : IRequest;
public record OrderShipped(int OrderId) : INotification;
public record Unhandled(int X);
public class OrdersController(IMediator mediator, IBus bus) {
    public async Task Ship(int id) { await mediator.Send(new ShipOrder(id)); }
    public async Task Notify(int id) { var evt = new OrderShipped(id); await mediator.Publish(evt); }
    public async Task Typed(int id) { await bus.Publish<OrderShipped>(new { OrderId = id }); }
    public async Task Nothing(int id) { await mediator.Send(new Unhandled(id)); }
}
public class ShipOrderHandler : IRequestHandler<ShipOrder> { public Task Handle(ShipOrder r, CancellationToken ct) { return Pack(); } Task Pack() => null; }
public class EmailOnShipped : INotificationHandler<OrderShipped> { public Task Handle(OrderShipped e, CancellationToken ct) => null; }
public class ShippedConsumer : IConsumer<OrderShipped> { public Task Consume(ConsumeContext<OrderShipped> c) => null; }
public interface IInvoiceMailer { void SendOverdue(int c); }
public class Billing(IInvoiceMailer mailer) {
    public void Remind(int c) { BackgroundJob.Enqueue(() => mailer.SendOverdue(c)); }
    public void Remind2(int c) { BackgroundJob.Enqueue<IInvoiceMailer>(m => m.SendOverdue(c)); }
}
public class Mailer : IInvoiceMailer { public void SendOverdue(int c) {} }
"""


@pytest.fixture()
def repo(tmp_path):
    pytest.importorskip("tree_sitter_c_sharp")
    (tmp_path / "Orders.cs").write_text(CS)
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "billing.py").write_text("from celery import shared_task\n\n@shared_task\ndef send_invoice(c):\n    return c\n\n"
                                                    "def not_a_task(c):\n    return c\n")
    (tmp_path / "tasks" / "views.py").write_text("from tasks.billing import send_invoice, not_a_task\n\n"
                                                  "def checkout(c):\n    send_invoice.delay(c)\n    not_a_task.delay(c)\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    languages._registry = None
    return tmp_path


def callers(g, node):
    return {c: g.edge_labels.get((c, node)) for c in g.nodes[node].called_by}


def test_message_buses_link_publishers_to_handlers(repo):
    g = build_query_graph(repo).graph
    assert callers(g, "Orders.cs.ShipOrderHandler.Handle") == {
        "Orders.cs.OrdersController.Ship": "Send ShipOrder -> IRequestHandler"}
    assert set(callers(g, "Orders.cs.EmailOnShipped.Handle")) == {"Orders.cs.OrdersController.Notify",
                                                                  "Orders.cs.OrdersController.Typed"}
    assert callers(g, "Orders.cs.ShippedConsumer.Consume")["Orders.cs.OrdersController.Notify"] == \
        "Publish OrderShipped -> IConsumer"  # MassTransit
    assert not [k for k in g.edge_labels if k[0] == "Orders.cs.OrdersController.Nothing"]  # no handler for Unhandled


def test_hangfire_jobs_are_labelled_and_typed(repo):
    g = build_query_graph(repo).graph
    got = callers(g, "Orders.cs.Mailer.SendOverdue")
    assert got == {"Orders.cs.Billing.Remind": "Hangfire Enqueue", "Orders.cs.Billing.Remind2": "Hangfire Enqueue"}


def test_celery_delay_reaches_the_task_only(repo):
    g = build_query_graph(repo).graph
    assert callers(g, "tasks.billing.send_invoice") == {"tasks.views.checkout": "Celery delay"}
    assert g.nodes["tasks.billing.not_a_task"].called_by == []  # .delay on an undecorated function


def test_output_marks_dispatch_edges(repo, monkeypatch):
    from daedalus.cli.main import main
    monkeypatch.chdir(repo)
    out = CliRunner().invoke(main, ["palace", "callers", "ShipOrderHandler.Handle"]).output
    assert "[via dispatch: Send ShipOrder -> IRequestHandler]" in out
    out = CliRunner().invoke(main, ["palace", "path", "OrdersController.Ship", "ShipOrderHandler.Pack"]).output
    assert "Ship -[Send ShipOrder -> IRequestHandler]-> Handle -> Pack" in out
    data = json.loads(CliRunner().invoke(main, ["palace", "impact", "ShipOrderHandler.Pack", "--json"]).output)
    assert data["callers"] == 2 and data["dispatch"] == ["Send ShipOrder -> IRequestHandler"]
    data = json.loads(CliRunner().invoke(main, ["palace", "callers", "Mailer.SendOverdue", "--json"]).output)
    assert {c["via"] for c in data["callers"]} == {"Hangfire Enqueue"}


def test_dispatch_reaches_tests_upstream_of_the_queue(repo):
    from daedalus.labyrinth.query import resolve_symbol, tests_reaching
    (repo / "Tests").mkdir()
    (repo / "Tests" / "OrdersTests.cs").write_text(
        "namespace Shop.Tests;\npublic class OrdersTests { [Fact] public async Task Ships() {"
        " await new OrdersController(null, null).Ship(1); } }\n")
    languages._registry = None
    g = build_query_graph(repo).graph
    assert tests_reaching(g, resolve_symbol(g, "ShipOrderHandler.Pack")) == ["Tests.OrdersTests.cs.OrdersTests.Ships"]


def _cs(tmp_path, files):
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    languages._registry = None
    return build_query_graph(tmp_path).graph


def test_message_types_resolve_by_namespace_and_bus_receivers(tmp_path):
    pytest.importorskip("tree_sitter_c_sharp")
    g = _cs(tmp_path, {
        "A.cs": "namespace A;\npublic record ShipOrder(int Id);\npublic class H : IRequestHandler<ShipOrder> { public Task Handle(ShipOrder r) => null; }\n"
                "public class P(IMediator m) { public Task Go() => m.Send(new ShipOrder(1)); }\n",
        "B.cs": "namespace B;\npublic record ShipOrder(int Id);\npublic class H2 : IRequestHandler<ShipOrder> { public Task Handle(ShipOrder r) => null; }\n",
        "Mail.cs": "namespace A;\nusing System.Net.Mail;\npublic record MailMessage(string To);\n"
                   "public class MailHandler : IRequestHandler<MailMessage> { public Task Handle(MailMessage m) => null; }\n"
                   "public class Notifier(SmtpClient smtp) { public void Go() { smtp.Send(new MailMessage(\"x\")); } }\n",
    })
    assert g.nodes["A.cs.H.Handle"].called_by == ["A.cs.P.Go"]
    assert g.nodes["B.cs.H2.Handle"].called_by == []  # B.ShipOrder isn't A.ShipOrder
    assert "Mail.cs.MailHandler.Handle" not in g.nodes["Mail.cs.Notifier.Go"].calls  # SmtpClient isn't a bus


def test_nullable_parameters_derived_handlers_and_direct_calls(tmp_path):
    pytest.importorskip("tree_sitter_c_sharp")
    g = _cs(tmp_path, {"S.cs": "namespace S;\npublic record Cmd(int X);\n"
                                "public class BaseH : IRequestHandler<Cmd> { public virtual Task Handle(Cmd c) => null; }\n"
                                "public class DerivedH : BaseH { public override Task Handle(Cmd c) => null; }\n"
                                "public class P(IMediator m, BaseH h) {\n"
                                "  public Task Go(Cmd? cmd) => m.Send(cmd);\n"
                                "  public Task Both() { h.Handle(new Cmd(1)); return m.Send(new Cmd(2)); }\n}\n"})
    assert {"S.cs.BaseH.Handle", "S.cs.DerivedH.Handle"} <= set(g.nodes["S.cs.P.Go"].calls)
    assert g.edge_labels.get(("S.cs.P.Go", "S.cs.DerivedH.Handle"))
    assert ("S.cs.P.Both", "S.cs.BaseH.Handle") not in g.edge_labels  # a direct call too: no dispatch label


def test_hangfire_labels_only_hangfire_lambdas_and_only_lambda_calls(tmp_path):
    pytest.importorskip("tree_sitter_c_sharp")
    g = _cs(tmp_path, {"J.cs": "namespace J;\npublic class W { public void Run() {} public void Prep() {} }\n"
                                "public class O { public void Run() {} }\n"
                                "public class U(W w, O o, Scheduler sched) {\n"
                                "  void A() { BackgroundJob.Enqueue(() => w.Run()); o.Run(); }\n"
                                "  void B() { sched.Schedule(() => w.Prep()); }\n"
                                "  void C() { BackgroundJob.Enqueue(() => w.Prep()); }\n}\n"})
    assert ("J.cs.U.A", "J.cs.O.Run") not in g.edge_labels      # called directly, outside the lambda
    assert ("J.cs.U.A", "J.cs.W.Run") not in g.edge_labels      # Run is also called directly in A
    assert ("J.cs.U.B", "J.cs.W.Prep") not in g.edge_labels     # not Hangfire
    assert g.edge_labels[("J.cs.U.C", "J.cs.W.Prep")] == "Hangfire Enqueue"


def test_generic_arguments_of_outside_types_dont_decide(tmp_path):
    pytest.importorskip("tree_sitter_c_sharp")
    g = _cs(tmp_path, {"G.cs": "namespace G;\npublic class Helper { public string Describe3() => \"\"; }\n"
                                "public class U { void M(System.Collections.Generic.List<int> l) { l.ConvertAll<System.Uri>(x => x.Describe3()); } }\n"})
    assert "G.cs.Helper.Describe3" in g.nodes["G.cs.U.M"].calls  # Uri says nothing certain: the name rule


def test_celery_module_attribute_form(tmp_path):
    g = _cs(tmp_path, {"app/__init__.py": "", "app/tasks.py": "from celery import shared_task\n\n@shared_task\ndef send(c):\n    return c\n",
                       "app/views.py": "from app import tasks\nimport app.tasks as t2\n\ndef go(c):\n    tasks.send.delay(c)\n\n"
                                       "def go2(c):\n    t2.send.apply_async((c,))\n"})
    assert g.edge_labels[("app.views.go", "app.tasks.send")] == "Celery delay"
    assert g.edge_labels[("app.views.go2", "app.tasks.send")] == "Celery apply_async"


def test_path_json_carries_labels(repo, monkeypatch):
    from daedalus.cli.main import main
    monkeypatch.chdir(repo)
    data = json.loads(CliRunner().invoke(main, ["palace", "path", "OrdersController.Ship", "ShipOrderHandler.Pack", "--json"]).output)
    assert data["via"] == {"Orders.cs.OrdersController.Ship -> Orders.cs.ShipOrderHandler.Handle": "Send ShipOrder -> IRequestHandler"}
