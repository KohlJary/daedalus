"""Each oracle must fail on the untouched fixture and pass on a reference solution."""
import subprocess, sys
sys.path.insert(0, ".")
from tasks import TASKS
from exp import make_repo, git, oracle

REF = {
    "add_sub": {"calc.py": TASKS["add_sub"]["files"]["calc.py"] + "\n\ndef sub(a, b):\n    return a - b\n"},
    "fix_mul": {"calc.py": TASKS["add_sub"]["files"]["calc.py"]},
    "mean_module": {"stats.py": "def mean(xs):\n    if not xs:\n        raise ValueError('empty')\n    return sum(xs) / len(xs)\n"},
    "slugify": {"slug.py": "import re\n\ndef slugify(text):\n    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')\n"},
    "duration": {"duration.py": TASKS["duration"]["files"]["duration.py"].replace("elif unit == \"m\":\n            total += n * 3600", "elif unit == \"m\":\n            total += n * 60")},
    "leap_year": {"dates.py": "DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]\n\ndef is_leap(y):\n    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)\n\ndef days_in_month(year, month):\n    return 29 if month == 2 and is_leap(year) else DAYS[month - 1]\n"},
    "word_count": {"text_utils.py": "def word_count(text):\n    return len(text.split())\n"},
    "inventory": {
        "inventory.py": TASKS["inventory"]["files"]["inventory.py"] + "\n    def remove(self, name, qty):\n        if qty <= 0 or qty > self.quantity(name):\n            raise ValueError('bad qty')\n        self.items[name] -= qty\n",
        "report.py": "def report(inv):\n    return \"\\n\".join(f\"{n}: {q}\" for n, q in sorted(inv.items.items()) if q > 0)\n"},
    "fib_perf": {"fib.py": "def fib(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\n"},
    "price_format": {"money.py": "def format_price(amount):\n    return f\"${amount:,.2f}\"\n"},
}
ok = True
for name, task in TASKS.items():
    base = oracle(task, "")["oracle_pass"]
    repo = make_repo(task["files"])
    for rel, content in REF[name].items():
        (repo / rel).write_text(content)
    git(repo, "add", "-A")
    ref = oracle(task, git(repo, "diff", "--cached", "HEAD").stdout)
    good = (base is False) and ref["oracle_pass"]
    ok &= good
    print(f"{name:13} base_fails={base is False!s:5} ref_passes={ref['oracle_pass']!s:5} {'' if good else 'PROBLEM ' + ref['oracle_out']}")
print("ALL OK" if ok else "FIX ORACLES")
