"""Compact interface summary of a codebase for a lean plan reviewer: per module, classes (fields, methods),
functions (signature, docstring, names called), and test function names."""
import ast


def _calls(node):
    names = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            names.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "?"))
    return sorted(names)


def _sig(fn):
    return f"{fn.name}({ast.unparse(fn.args)})"


def summarize(files: dict) -> str:
    out = []
    for path, src in sorted(files.items()):
        if not path.endswith(".py") or not src.strip():
            continue
        tree = ast.parse(src)
        if path.startswith("tests/"):
            tests = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
            asserts = [ast.unparse(a.test) for n in tree.body if isinstance(n, ast.FunctionDef)
                       for a in ast.walk(n) if isinstance(a, ast.Assert)]
            out.append(f"{path}: tests {tests}; asserts: " + " | ".join(asserts))
            continue
        lines = [f"{path}:"]
        imports = [ast.unparse(n) for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        if imports:
            lines.append("  imports: " + "; ".join(imports))
        for n in tree.body:
            if isinstance(n, ast.ClassDef):
                deco = ",".join(ast.unparse(d) for d in n.decorator_list)
                fields = [ast.unparse(s) for s in n.body if isinstance(s, ast.AnnAssign)]
                lines.append(f"  class {n.name}" + (f" @{deco}" if deco else "") + (f" fields: {fields}" if fields else ""))
                for m in n.body:
                    if isinstance(m, ast.FunctionDef):
                        lines.append(f"    def {_sig(m)}  calls={_calls(m)}")
            elif isinstance(n, ast.FunctionDef):
                doc = ast.get_docstring(n)
                lines.append(f"  def {_sig(n)}  calls={_calls(n)}" + (f'  """{doc}"""' if doc else ""))
            elif isinstance(n, ast.Assign):
                lines.append(f"  {ast.unparse(n)[:120]}")
        out.append("\n".join(lines))
    return "\n".join(out)
