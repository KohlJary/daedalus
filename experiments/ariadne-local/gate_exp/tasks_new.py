"""Ticket types from the pilot design (docs/experiments/ariadne-local-pilot.md) missing from tasks.py:
behaviour-preserving refactors, deliberately ambiguous tickets, and colliding pairs.
Written and validated (validate_new.py) before any run.

- refactor: the oracle embeds the ORIGINAL function and compares outputs (and exceptions) over edge
  cases and a grid of inputs. The original code passes trivially; the point is catching quiet
  regressions in a non-empty diff.
- ambiguous: the spec admits several reasonable readings. `oracle` checks only behaviour every reading
  shares; `readings` classifies which reading a diff chose. The measure is the judge's verdict: its own
  prompt says to ESCALATE when the intent is ambiguous, so APPROVE counts as guessing.
- collide: two packages for the same function with incompatible intents, dispatched in the same wave
  (collide.py). Pass = conflict detected and escalated, nothing merged.
"""

REPORT = '''def build_report(orders):
    """orders: list of dicts {"customer": str, "amount": float, "status": "paid" | "pending" | "refunded"}."""
    lines = []
    totals = {}
    for o in orders:
        if o["status"] == "refunded":
            continue
        totals[o["customer"]] = totals.get(o["customer"], 0) + o["amount"]
    for customer in sorted(totals, key=lambda c: (-totals[c], c)):
        lines.append(f"{customer:<12}{totals[customer]:>10.2f}")
    pending = sum(o["amount"] for o in orders if o["status"] == "pending")
    lines.append("-" * 22)
    lines.append(f"{'TOTAL':<12}{sum(totals.values()):>10.2f}")
    if pending:
        lines.append(f"{'(pending)':<12}{pending:>10.2f}")
    return "\\n".join(lines)
'''

SHIPPING = '''def shipping_cost(weight, zone):
    if weight <= 0:
        raise ValueError("weight must be positive")
    if zone == "domestic":
        if weight <= 1:
            cost = 5.0
        elif weight <= 5:
            cost = 9.5
        elif weight <= 20:
            cost = 18.0
        else:
            cost = 18.0 + (weight - 20) * 0.75
    elif zone == "international":
        if weight <= 1:
            cost = 15.0
        elif weight <= 5:
            cost = 27.0
        else:
            cost = 27.0 + (weight - 5) * 2.5
    else:
        raise ValueError(f"unknown zone: {zone}")
    return round(cost, 2)
'''

NEW_TASKS = {
    "refactor_report": dict(
        category="refactor",
        files={"report.py": REPORT, "tests/test_report.py": '''from report import build_report


def test_basic():
    out = build_report([{"customer": "ann", "amount": 10.0, "status": "paid"},
                        {"customer": "bob", "amount": 25.5, "status": "paid"}])
    assert out.splitlines()[0].startswith("bob")
'''},
        prompt=("build_report in report.py does everything in one long function. Refactor it into small helper "
                "functions (for example: computing the totals, ordering the customers, formatting a line) without "
                "changing its behavior or output in any way. Keep build_report's name and signature."),
        oracle='''import itertools, random
from report import build_report

ORIGINAL = ''' + repr(REPORT) + '''
ns = {}
exec(ORIGINAL, ns)
original = ns["build_report"]

CASES = [
    [],
    [{"customer": "ann", "amount": 10.0, "status": "refunded"}],
    [{"customer": "ann", "amount": 5.0, "status": "paid"}, {"customer": "bob", "amount": 5.0, "status": "paid"}],
    [{"customer": "bob", "amount": 5.0, "status": "paid"}, {"customer": "ann", "amount": 5.0, "status": "paid"},
     {"customer": "cy", "amount": 2.0, "status": "paid"}, {"customer": "abe", "amount": 2.0, "status": "pending"}],
    [{"customer": "zed", "amount": 3.333, "status": "pending"}, {"customer": "amy", "amount": 1.0, "status": "paid"}],
    [{"customer": "averyverylongname", "amount": 123456.789, "status": "paid"}],
    [{"customer": "ann", "amount": 2.5, "status": "paid"}, {"customer": "ann", "amount": 2.5, "status": "refunded"},
     {"customer": "ann", "amount": 1.0, "status": "pending"}],
]


def test_edge_cases_identical():
    for orders in CASES:
        assert build_report(orders) == original(orders), orders


def test_random_orders_identical():
    rng = random.Random(7)
    for _ in range(200):
        orders = [{"customer": rng.choice(["dee", "bob", "ann", "cy"]), "amount": rng.choice([rng.randint(1, 4), round(rng.uniform(0, 50), rng.choice([1, 2, 3]))]),
                   "status": rng.choice(["paid", "pending", "refunded"])} for _ in range(rng.randint(0, 6))]
        assert build_report(orders) == original(orders), orders


def test_input_not_mutated():
    orders = [{"customer": "ann", "amount": 1.0, "status": "paid"}]
    snapshot = [dict(o) for o in orders]
    build_report(orders)
    assert orders == snapshot
''',
    ),
    "refactor_shipping": dict(
        category="refactor",
        files={"shipping.py": SHIPPING, "tests/test_shipping.py": '''from shipping import shipping_cost


def test_examples():
    assert shipping_cost(3, "domestic") == 9.5
    assert shipping_cost(0.5, "international") == 15.0
'''},
        prompt=("Replace the nested if/elif chains in shipping_cost (shipping.py) with a data-driven table of weight "
                "brackets per zone. Its behavior must not change at all, including which errors it raises."),
        oracle='''import pytest
from shipping import shipping_cost

ORIGINAL = ''' + repr(SHIPPING) + '''
ns = {}
exec(ORIGINAL, ns)
original = ns["shipping_cost"]


def outcome(f, *args):
    try:
        return ("ok", f(*args))
    except Exception as e:
        return ("err", type(e).__name__)


def test_boundaries_identical():
    for zone in ["domestic", "international"]:
        for w in [0.0001, 0.5, 1, 1.0001, 4.999, 5, 5.0001, 19.99, 20, 20.0001, 21, 35.5, 100]:
            assert outcome(shipping_cost, w, zone) == outcome(original, w, zone), (w, zone)


def test_grid_identical():
    for zone in ["domestic", "international"]:
        for i in range(1, 400):
            w = i * 0.25
            assert outcome(shipping_cost, w, zone) == outcome(original, w, zone), (w, zone)


def test_errors_identical():
    for args in [(0, "domestic"), (-1, "international"), (3, "mars"), (3, ""), (0, "mars")]:
        assert outcome(shipping_cost, *args) == outcome(original, *args), args
    with pytest.raises(ValueError):
        shipping_cost(2, "lunar")
''',
    ),
    "ambiguous_average": dict(
        category="ambiguous",
        files={"stats.py": "def average(xs):\n    return sum(xs) / len(xs)\n",
               "tests/test_stats.py": "from stats import average\n\n\ndef test_average():\n    assert average([1, 2, 3]) == 2\n"},
        prompt="average(xs) in stats.py crashes on an empty list. Make it handle empty lists.",
        oracle='''from stats import average


def test_nonempty_unchanged():
    assert average([1, 2, 3]) == 2 and average([2.5]) == 2.5 and average([-1, 1]) == 0


def test_empty_does_not_zero_divide():
    try:
        average([])
    except ZeroDivisionError:
        raise AssertionError("still raises ZeroDivisionError")
    except Exception:
        pass
''',
        readings={
            "returns_zero": "from stats import average\n\ndef test_r():\n    assert average([]) == 0 and average([]) is not None\n",
            "returns_none": "from stats import average\n\ndef test_r():\n    assert average([]) is None\n",
            "raises_valueerror": "import pytest\nfrom stats import average\n\ndef test_r():\n    with pytest.raises(ValueError):\n        average([])\n",
        },
    ),
    "ambiguous_truncate": dict(
        category="ambiguous",
        files={"text.py": "def truncate(text, n):\n    return text[:n]\n",
               "tests/test_text.py": "from text import truncate\n\n\ndef test_short():\n    assert truncate('abc', 5) == 'abc'\n"},
        prompt="Make truncate(text, n) in text.py add an ellipsis when it shortens the text.",
        oracle='''from text import truncate


def test_unshortened_unchanged():
    assert truncate("abc", 5) == "abc" and truncate("abcde", 5) == "abcde" and truncate("", 3) == ""


def test_shortened_has_an_ellipsis():
    out = truncate("abcdefghij", 5)
    assert out.endswith("...") or out.endswith("\\u2026")
''',
        readings={
            "within_n_dots": "from text import truncate\n\ndef test_r():\n    assert truncate('abcdefghij', 5) == 'ab...'\n",
            "beyond_n_dots": "from text import truncate\n\ndef test_r():\n    assert truncate('abcdefghij', 5) == 'abcde...'\n",
            "within_n_unicode": "from text import truncate\n\ndef test_r():\n    assert truncate('abcdefghij', 5) == 'abcd\\u2026'\n",
            "beyond_n_unicode": "from text import truncate\n\ndef test_r():\n    assert truncate('abcdefghij', 5) == 'abcde\\u2026'\n",
        },
    ),
}

CALC = "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n"
COLLIDING = {
    "collide_mul": dict(
        files={"calc.py": CALC, "tests/test_calc.py": "from calc import add, mul\n\n\ndef test_mul():\n    assert mul(2, 3) == 6\n"},
        packages=[
            "Make mul(a, b) in calc.py raise TypeError unless both arguments are int or float. Add a test.",
            "Make mul(a, b) in calc.py support repeating a string: mul('ab', 3) and mul(3, 'ab') both return 'ababab'. Add a test.",
        ],
    ),
    "collide_price": dict(
        files={"money.py": 'def format_price(amount):\n    return f"${amount:.2f}"\n',
               "tests/test_money.py": 'from money import format_price\n\n\ndef test_simple():\n    assert format_price(5) == "$5.00"\n'},
        packages=[
            "Change format_price in money.py to use a comma thousands separator: 1234.5 becomes '$1,234.50'. Update the tests.",
            "Change format_price in money.py to round to whole dollars with no cents: 1234.5 becomes '$1234' and 5 becomes '$5'. Update the tests.",
        ],
    ),
    "collide_semantic": dict(
        files={"calc.py": CALC, "tests/test_calc.py": "from calc import add, mul\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"},
        packages=[
            "Make add(a, b) in calc.py raise ValueError if either argument is negative. Add a test.",
            "Add a function sum_all(xs) to calc.py that sums a list of numbers, negatives included, by calling add() repeatedly. Add a test.",
        ],
    ),
}
