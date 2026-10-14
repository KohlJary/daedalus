"""Reference implementations of the greenfield specs, used only to validate the oracles."""

UNITS = {
    "units/__init__.py": '''import math
import re
from dataclasses import dataclass

FACTORS = {
    "length": {"mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0, "in": 0.0254, "ft": 0.3048, "mi": 1609.344},
    "mass": {"g": 0.001, "kg": 1.0, "lb": 0.45359237, "oz": 0.028349523125},
    "time": {"ms": 0.001, "s": 1.0, "min": 60.0, "h": 3600.0, "day": 86400.0},
}
DIMENSION = {u: d for d, units in FACTORS.items() for u in units}


class UnknownUnitError(ValueError):
    pass


class DimensionError(ValueError):
    pass


@dataclass(frozen=True, eq=False)
class Quantity:
    value: float
    unit: str

    def __post_init__(self):
        if self.unit not in DIMENSION:
            raise UnknownUnitError(self.unit)
        object.__setattr__(self, "value", float(self.value))

    @property
    def dimension(self):
        return DIMENSION[self.unit]

    def _base(self):
        return self.value * FACTORS[self.dimension][self.unit]

    def to(self, unit):
        if unit not in DIMENSION:
            raise UnknownUnitError(unit)
        if DIMENSION[unit] != self.dimension:
            raise DimensionError(f"{self.unit} -> {unit}")
        return Quantity(self._base() / FACTORS[self.dimension][unit], unit)

    def _same(self, other):
        if not isinstance(other, Quantity):
            return NotImplemented
        if other.dimension != self.dimension:
            raise DimensionError(f"{self.unit} vs {other.unit}")
        return other

    def __add__(self, other):
        o = self._same(other)
        return o if o is NotImplemented else Quantity(self.value + o.to(self.unit).value, self.unit)

    def __sub__(self, other):
        o = self._same(other)
        return o if o is NotImplemented else Quantity(self.value - o.to(self.unit).value, self.unit)

    def __mul__(self, n):
        if isinstance(n, Quantity):
            raise TypeError("Quantity * Quantity is not supported")
        return Quantity(self.value * n, self.unit)

    __rmul__ = __mul__

    def __truediv__(self, n):
        if isinstance(n, Quantity):
            raise TypeError("Quantity / Quantity is not supported")
        return Quantity(self.value / n, self.unit)

    def __eq__(self, other):
        if not isinstance(other, Quantity):
            return NotImplemented
        if other.dimension != self.dimension:
            return False
        return math.isclose(self._base(), other._base(), rel_tol=1e-9, abs_tol=1e-12)

    def __lt__(self, other):
        return self._base() < self._same(other)._base() and not self == other

    def __le__(self, other):
        return self._base() < self._same(other)._base() or self == other

    def __gt__(self, other):
        return self._base() > self._same(other)._base() and not self == other

    def __ge__(self, other):
        return self._base() > self._same(other)._base() or self == other

    def __str__(self):
        return format_quantity(self)


_NUM = re.compile(r"^\\s*([-+]?(?:\\d+\\.?\\d*|\\.\\d+)(?:[eE][-+]?\\d+)?)\\s*([A-Za-z]+)\\s*$")


def parse(text):
    m = _NUM.match(text)
    if not m:
        raise ValueError(f"cannot parse quantity: {text!r}")
    return Quantity(float(m.group(1)), m.group(2))


def format_quantity(q, precision=2):
    return f"{q.value:.{precision}f} {q.unit}"


def convert(text, unit):
    return format_quantity(parse(text).to(unit))
''',
    "units/__main__.py": '''import sys
from units import convert

try:
    print(convert(sys.argv[1], sys.argv[2]))
except (ValueError, IndexError) as e:
    print(f"error: {e}", file=sys.stderr)
    sys.exit(2)
''',
}

KVSTORE = {
    "kvstore/__init__.py": '''import json
import time

_MISSING = object()


class NoTransactionError(RuntimeError):
    pass


class TransactionOpenError(RuntimeError):
    pass


class Store:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._data = {}      # key -> (value, expires_at or None)
        self._tx = []        # stack of {key: entry or _MISSING (deleted)}

    def _lookup(self, key):
        for layer in reversed(self._tx):
            if key in layer:
                entry = layer[key]
                break
        else:
            entry = self._data.get(key, _MISSING)
        if entry is _MISSING:
            return _MISSING
        value, exp = entry
        if exp is not None and self.clock() >= exp:
            return _MISSING
        return entry

    def _write(self, key, entry):
        if self._tx:
            self._tx[-1][key] = entry
        elif entry is _MISSING:
            self._data.pop(key, None)
        else:
            self._data[key] = entry

    def set(self, key, value, ttl=None):
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be positive")
        self._write(key, (value, None if ttl is None else self.clock() + ttl))

    def get(self, key, default=None):
        entry = self._lookup(key)
        return default if entry is _MISSING else entry[0]

    def delete(self, key):
        if self._lookup(key) is _MISSING:
            return False
        self._write(key, _MISSING)
        return True

    def _all_keys(self):
        keys = set(self._data)
        for layer in self._tx:
            keys |= set(layer)
        return keys

    def keys(self):
        return sorted(k for k in self._all_keys() if self._lookup(k) is not _MISSING)

    def __len__(self):
        return len(self.keys())

    def __contains__(self, key):
        return self._lookup(key) is not _MISSING

    def ttl(self, key):
        entry = self._lookup(key)
        if entry is _MISSING:
            raise KeyError(key)
        return None if entry[1] is None else entry[1] - self.clock()

    def begin(self):
        self._tx.append({})

    def rollback(self):
        if not self._tx:
            raise NoTransactionError("no transaction")
        self._tx.pop()

    def commit(self):
        if not self._tx:
            raise NoTransactionError("no transaction")
        layer = self._tx.pop()
        for key, entry in layer.items():
            self._write(key, entry)

    def snapshot(self):
        if self._tx:
            raise TransactionOpenError("transaction open")
        out = {}
        for k in self.keys():
            value, exp = self._data[k]
            out[k] = {"value": value, "expires_in": None if exp is None else exp - self.clock()}
        return json.dumps(out, sort_keys=True)

    @classmethod
    def restore(cls, snapshot, clock=time.monotonic):
        s = cls(clock=clock)
        for k, item in json.loads(snapshot).items():
            s.set(k, item["value"], ttl=item["expires_in"])
        return s
''',
    "kvstore/commands.py": '''import math

from kvstore import NoTransactionError


def execute(store, line):
    parts = line.split()
    if not parts:
        return "ERR unknown command"
    cmd, args = parts[0].upper(), parts[1:]
    if cmd == "SET" and len(args) == 2:
        store.set(args[0], args[1])
        return "OK"
    if cmd == "SET" and len(args) == 4 and args[2].upper() == "EX":
        store.set(args[0], args[1], ttl=int(args[3]))
        return "OK"
    if cmd == "GET" and len(args) == 1:
        v = store.get(args[0])
        return "(nil)" if v is None else str(v)
    if cmd == "DEL" and len(args) == 1:
        return "1" if store.delete(args[0]) else "0"
    if cmd == "KEYS" and not args:
        return " ".join(store.keys()) or "(empty)"
    if cmd == "TTL" and len(args) == 1:
        try:
            t = store.ttl(args[0])
        except KeyError:
            return "-2"
        return "-1" if t is None else str(math.floor(t))
    if cmd == "BEGIN" and not args:
        store.begin()
        return "OK"
    if cmd in ("COMMIT", "ROLLBACK") and not args:
        try:
            store.commit() if cmd == "COMMIT" else store.rollback()
        except NoTransactionError:
            return "ERR no transaction"
        return "OK"
    return "ERR unknown command"
''',
}

# Plausible bugs each oracle must catch
UNITS_BUGS = [("units/__init__.py", '"mi": 1609.344', '"mi": 1609.0'),
              ("units/__init__.py", "Quantity(self.value + o.to(self.unit).value, self.unit)", "Quantity(self.value + o.value, self.unit)")]
KVSTORE_BUGS = [("kvstore/__init__.py", "if exp is not None and self.clock() >= exp:", "if exp is not None and self.clock() > exp + 1:"),
                ("kvstore/__init__.py", "        self._tx.pop()\n\n    def commit", "        pass\n\n    def commit")]
