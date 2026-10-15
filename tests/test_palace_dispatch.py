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
