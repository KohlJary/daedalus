"""Greenfield specs for the 'Ariadne gets the shape down, a frontier model polishes' question.
Each spec fixes the public interface exactly, so the hidden oracle can test any correct implementation."""

UNITS_SPEC = """# Spec: units, a small unit-conversion library

Build a Python package `units` (directory `units/` at the project root) with tests in `tests/`.

## Units
Three dimensions, each with a base unit and each unit's factor to the base:
- length (base `m`): `mm` 0.001, `cm` 0.01, `m` 1, `km` 1000, `in` 0.0254, `ft` 0.3048, `mi` 1609.344
- mass (base `kg`): `g` 0.001, `kg` 1, `lb` 0.45359237, `oz` 0.028349523125
- time (base `s`): `ms` 0.001, `s` 1, `min` 60, `h` 3600, `day` 86400

Unit symbols are case-sensitive.

## Errors (importable from `units`)
- `UnknownUnitError`, a subclass of `ValueError`: an unknown unit symbol.
- `DimensionError`, a subclass of `ValueError`: an operation mixing dimensions.

## API (importable from `units`)
- `Quantity(value, unit)`: immutable, with attributes `.value` (float) and `.unit` (str). Raises `UnknownUnitError` for an unknown unit.
- `Quantity.to(unit)` returns a new Quantity in `unit`. Converting to a unit of another dimension raises `DimensionError`.
- `q1 + q2` and `q1 - q2` return a Quantity in q1's unit. Different dimensions raise `DimensionError`.
- `q * n`, `n * q` and `q / n` for a number `n` return a Quantity in q's unit. `q1 * q2` raises `TypeError`.
- Comparisons `==`, `<`, `<=`, `>`, `>=` between quantities of the same dimension compare physical amounts, with equality as `math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)` on the base-unit values. Across dimensions `==` is False and the ordering operators raise `DimensionError`.
- `parse(text)` returns a Quantity from a number followed by a unit, with optional whitespace between them and around them: `"5 km"`, `"5km"`, `"-2.5 h"`, `"1e3 m"`, `"  7 g "`. A valid number with an unknown unit raises `UnknownUnitError`; anything else raises `ValueError`.
- `format_quantity(q, precision=2)` returns the value with `precision` decimals, a space, and the unit: `"5.00 km"`. `str(q)` equals `format_quantity(q)`.
- `convert(text, unit)` parses, converts and formats: `convert("1 mi", "km") == "1.61 km"`.

## CLI
`python -m units "<quantity>" <unit>` prints `convert(...)` and exits 0. On invalid input it prints a message to stderr and exits 2.
"""

KVSTORE_SPEC = """# Spec: kvstore, an in-memory key-value store with TTLs and transactions

Build a Python package `kvstore` (directory `kvstore/` at the project root) with tests in `tests/`.

## Store (importable from `kvstore`)
`Store(clock=time.monotonic)`: `clock` is a zero-argument callable returning seconds; tests pass a fake one.
- `set(key, value, ttl=None)`: `ttl` is seconds from now; `ttl <= 0` raises `ValueError`. Setting a key replaces its value and its TTL.
- `get(key, default=None)`: an expired key behaves exactly like an absent one.
- `delete(key)` returns True if a live key was removed, else False.
- `keys()` returns the live keys, sorted.
- `len(store)` is the number of live keys; `key in store` is True for a live key.
- `ttl(key)` returns the remaining seconds (float) for a live key with a TTL, None for a live key without one, and raises `KeyError` for an absent or expired key.

## Transactions
- `begin()` opens a transaction; transactions nest.
- Reads inside a transaction see its writes and deletes.
- `rollback()` discards the innermost open transaction's writes and deletes.
- `commit()` applies the innermost open transaction to its parent transaction, or to the store if it is the outermost.
- `commit()` or `rollback()` with no open transaction raises `NoTransactionError`, a subclass of `RuntimeError` importable from `kvstore`.

## Snapshots
- `snapshot()` returns a JSON string of the live keys: an object mapping each key to `{"value": value, "expires_in": seconds or null}`, keys sorted. With a transaction open it raises `TransactionOpenError`, a subclass of `RuntimeError` importable from `kvstore`.
- `Store.restore(snapshot, clock=time.monotonic)` (a classmethod) returns a new Store; `expires_in` counts from the time of the restore.

## Commands (`kvstore/commands.py`)
`execute(store, line)` runs one command and returns its reply as a string. Command names are case-insensitive; keys and values are single words.
- `SET key value` -> `OK`; `SET key value EX seconds` sets a TTL (an integer number of seconds) -> `OK`
- `GET key` -> the value, or `(nil)`
- `DEL key` -> `1` if a live key was removed, else `0`
- `KEYS` -> the live keys separated by single spaces, or `(empty)`
- `TTL key` -> remaining seconds rounded down to an integer, `-1` for a key without a TTL, `-2` for an absent key
- `BEGIN`, `COMMIT`, `ROLLBACK` -> `OK`, or `ERR no transaction` when there is none to commit or roll back
- anything else -> `ERR unknown command`
"""

UNITS_ORACLE = '''import math, subprocess, sys
import pytest
from units import Quantity, parse, format_quantity, convert, UnknownUnitError, DimensionError


def close(a, b):
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)


def test_errors_are_valueerrors():
    assert issubclass(UnknownUnitError, ValueError) and issubclass(DimensionError, ValueError)


def test_quantity_basics_and_immutability():
    q = Quantity(5, "km")
    assert q.value == 5 and q.unit == "km"
    with pytest.raises(Exception):
        q.value = 6
    with pytest.raises(UnknownUnitError):
        Quantity(1, "parsec")
    with pytest.raises(UnknownUnitError):
        Quantity(1, "KM")


def test_conversions():
    assert close(Quantity(1, "mi").to("km").value, 1.609344)
    assert close(Quantity(12, "in").to("ft").value, 1.0)
    assert close(Quantity(1, "lb").to("oz").value, 16.0)
    assert close(Quantity(1, "day").to("min").value, 1440.0)
    assert Quantity(1, "day").to("min").unit == "min"
    with pytest.raises(DimensionError):
        Quantity(1, "kg").to("m")


def test_arithmetic():
    s = Quantity(1, "km") + Quantity(500, "m")
    assert s.unit == "km" and close(s.value, 1.5)
    d = Quantity(1, "h") - Quantity(30, "min")
    assert d.unit == "h" and close(d.value, 0.5)
    assert close((Quantity(2, "kg") * 3).value, 6) and close((3 * Quantity(2, "kg")).value, 6)
    assert close((Quantity(9, "s") / 3).value, 3) and (Quantity(9, "s") / 3).unit == "s"
    with pytest.raises(DimensionError):
        Quantity(1, "kg") + Quantity(1, "m")
    with pytest.raises(TypeError):
        Quantity(1, "m") * Quantity(1, "m")


def test_comparisons():
    assert Quantity(1, "km") == Quantity(1000, "m")
    assert Quantity(1, "ft") < Quantity(1, "m") and Quantity(1, "m") >= Quantity(100, "cm")
    assert Quantity(1, "kg") > Quantity(1, "lb") and Quantity(1, "g") <= Quantity(1, "oz")
    assert not (Quantity(1, "m") == Quantity(1, "s"))
    with pytest.raises(DimensionError):
        Quantity(1, "m") < Quantity(1, "s")


def test_parse():
    for text, value, unit in [("5 km", 5, "km"), ("5km", 5, "km"), ("-2.5 h", -2.5, "h"), ("1e3 m", 1000, "m"), ("  7 g ", 7, "g")]:
        q = parse(text)
        assert close(q.value, value) and q.unit == unit, text
    with pytest.raises(UnknownUnitError):
        parse("5 parsec")
    for bad in ["km", "5", "", "five km", "5 k m"]:
        with pytest.raises(ValueError):
            parse(bad)


def test_format_and_convert():
    assert format_quantity(Quantity(5, "km")) == "5.00 km"
    assert format_quantity(Quantity(1 / 3, "h"), precision=4) == "0.3333 h"
    assert str(Quantity(2.5, "kg")) == "2.50 kg"
    assert convert("1 mi", "km") == "1.61 km"
    assert convert("90 min", "h") == "1.50 h"


def test_cli():
    ok = subprocess.run([sys.executable, "-m", "units", "1 mi", "km"], capture_output=True, text=True)
    assert ok.returncode == 0 and ok.stdout.strip() == "1.61 km"
    bad = subprocess.run([sys.executable, "-m", "units", "1 mi", "kg"], capture_output=True, text=True)
    assert bad.returncode == 2 and bad.stderr.strip()
'''

KVSTORE_ORACLE = '''import json
import pytest
from kvstore import Store, NoTransactionError, TransactionOpenError
from kvstore.commands import execute


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


def test_basic_ops(clock):
    s = Store(clock=clock)
    s.set("a", 1); s.set("b", "two")
    assert s.get("a") == 1 and s.get("zz", "d") == "d"
    assert s.keys() == ["a", "b"] and len(s) == 2 and "a" in s
    assert s.delete("a") is True and s.delete("a") is False and s.keys() == ["b"]


def test_ttl(clock):
    s = Store(clock=clock)
    s.set("k", "v", ttl=10)
    s.set("p", "v")
    assert s.ttl("p") is None and abs(s.ttl("k") - 10) < 1e-9
    clock.t += 4
    assert abs(s.ttl("k") - 6) < 1e-9
    clock.t += 6
    assert s.get("k") is None and "k" not in s and s.keys() == ["p"] and len(s) == 1
    with pytest.raises(KeyError):
        s.ttl("k")
    assert s.delete("k") is False
    with pytest.raises(ValueError):
        s.set("x", 1, ttl=0)
    s.set("r", 1, ttl=5); s.set("r", 2)
    clock.t += 100
    assert s.get("r") == 2


def test_transactions(clock):
    s = Store(clock=clock)
    s.set("a", 1)
    s.begin(); s.set("a", 2); s.set("b", 3)
    assert s.get("a") == 2 and s.keys() == ["a", "b"]
    s.rollback()
    assert s.get("a") == 1 and s.get("b") is None
    s.begin(); s.delete("a")
    assert s.get("a") is None
    s.rollback()
    assert s.get("a") == 1
    s.begin(); s.set("a", 10); s.begin(); s.set("a", 20); s.rollback()
    assert s.get("a") == 10
    s.begin(); s.set("c", 5); s.commit()
    assert s.get("c") == 5
    s.commit()
    assert s.get("a") == 10 and s.get("c") == 5
    with pytest.raises(NoTransactionError):
        s.commit()
    with pytest.raises(NoTransactionError):
        s.rollback()
    assert issubclass(NoTransactionError, RuntimeError)


def test_nested_commit_then_outer_rollback(clock):
    s = Store(clock=clock)
    s.begin(); s.begin(); s.set("x", 1); s.commit(); s.rollback()
    assert s.get("x") is None


def test_snapshot_restore(clock):
    s = Store(clock=clock)
    s.set("b", [1, 2]); s.set("a", "x", ttl=30)
    snap = json.loads(s.snapshot())
    assert list(snap) == ["a", "b"]
    assert snap["b"] == {"value": [1, 2], "expires_in": None}
    assert abs(snap["a"]["expires_in"] - 30) < 1e-9
    clock2 = Clock(); clock2.t = 5.0
    r = Store.restore(s.snapshot(), clock=clock2)
    assert r.get("b") == [1, 2] and abs(r.ttl("a") - 30) < 1e-9
    clock2.t += 31
    assert r.get("a") is None
    s.begin()
    with pytest.raises(TransactionOpenError):
        s.snapshot()
    assert issubclass(TransactionOpenError, RuntimeError)


def test_commands(clock):
    s = Store(clock=clock)
    assert execute(s, "SET a 1") == "OK" and execute(s, "get a") == "1"
    assert execute(s, "GET nope") == "(nil)"
    assert execute(s, "KEYS") == "a"
    assert execute(s, "SET t v EX 10") == "OK"
    clock.t += 2.5
    assert execute(s, "TTL t") == "7" and execute(s, "TTL a") == "-1" and execute(s, "TTL zz") == "-2"
    assert execute(s, "DEL a") == "1" and execute(s, "DEL a") == "0"
    assert execute(s, "ROLLBACK") == "ERR no transaction" and execute(s, "COMMIT") == "ERR no transaction"
    assert execute(s, "BEGIN") == "OK" and execute(s, "SET q 9") == "OK" and execute(s, "ROLLBACK") == "OK"
    assert execute(s, "GET q") == "(nil)"
    assert execute(s, "FLY away") == "ERR unknown command"
    s2 = Store(clock=clock)
    assert execute(s2, "KEYS") == "(empty)"
'''
