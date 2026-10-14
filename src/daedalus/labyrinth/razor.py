"""
Razor (.razor Blazor components, .cshtml views and pages) for the palace.

A component compiles to a class named for its file, so each file becomes a class element. Its C# lives
in @code / @functions / @{ } blocks, which are parsed with the C# tree-sitter grammar (line numbers
mapped back to the file) and become that class's methods. The markup's references become the class's
calls: components used as tags (<Counter />), handlers (@onclick="Increment"), and expressions
(@FormatPrice(item), @(Total())).
"""

import re
from pathlib import Path
from typing import List, Optional, Tuple

from .languages import AnchorPattern, CodeElement, LanguageSupport

CODE_BLOCK = re.compile(r"@(?:code|functions)\s*\{|@\{")
COMPONENT_TAG = re.compile(r"<([A-Z][\w.]*)(?=[\s/>]|<)")
HANDLER = re.compile(r"@on\w+(?::\w+)?\s*=\s*\"([^\"]*)\"")
CALL = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\s*\(")
RAZOR_KEYWORDS = {"if", "foreach", "for", "while", "switch", "using", "code", "functions", "page", "inject",
                  "model", "inherits", "implements", "layout", "attribute", "typeparam", "namespace", "await",
                  "async", "section", "RenderBody", "RenderSection", "Html", "Url", "nameof", "typeof", "new",
                  "var", "in", "return", "catch", "lock", "default", "sizeof", "checked", "unchecked"}


def _close(text: str, open_at: int) -> int:
    """Index of the brace closing the one at open_at, skipping C# strings ("", @"", $"", '') and comments."""
    depth = 0
    i = open_at
    n = len(text)
    while i < n:
        c = text[i]
        if c == "/" and text.startswith("//", i):
            i = text.find("\n", i)
            i = n if i < 0 else i
            continue
        if c == "/" and text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        if c == '"':
            verbatim = i > 0 and text[i - 1] == "@" or (i > 1 and text[i - 2:i] in ("@$", "$@"))
            i += 1
            while i < n:
                if text[i] == "\\" and not verbatim:
                    i += 2
                    continue
                if text[i] == '"':
                    if verbatim and text.startswith('""', i):
                        i += 2
                        continue
                    break
                i += 1
            i += 1
            continue
        if c == "'":
            end = text.find("'", i + 3 if text[i + 1:i + 2] == "\\" else i + 1)
            i = n if end < 0 else end + 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return n - 1


def markup_references(markup: str) -> List[str]:
    """Names the markup calls: component tags (<Counter />, <Layout.Header />, <Item<int> />), handler
    values (@onclick="Save", "@(() => Save())", "async () => await Load()"), and calls in Razor
    expressions and control flow (@Format(x), @(Total()), @foreach (var i in GetItems())). @bind values
    are fields, not calls; member calls (item.ToString()) are left out."""
    refs = set()
    for tag in COMPONENT_TAG.findall(markup):
        refs.add(tag.split(".")[-1])
    for value in HANDLER.findall(markup):
        value = value.strip().lstrip("@")
        if re.fullmatch(r"[A-Za-z_]\w*", value):
            refs.add(value)
        else:
            refs.update(CALL.findall(value))
    for m in re.finditer(r"@", markup):
        line_end = markup.find("\n", m.end())
        refs.update(CALL.findall(markup[m.end(): len(markup) if line_end < 0 else line_end]))
    return sorted(refs - RAZOR_KEYWORDS)


class RazorSupport(LanguageSupport):
    """Razor files, analyzed through the C# support's grammar."""

    package_markers = ("_Imports.razor",)

    def __init__(self, csharp: LanguageSupport):
        self.csharp = csharp

    @property
    def name(self) -> str:
        return "Razor"

    @property
    def extensions(self) -> List[str]:
        return [".razor", ".cshtml"]

    def available(self) -> bool:
        return getattr(self.csharp, "available", lambda: False)()

    def blocks(self, text: str) -> List[Tuple[int, int]]:
        """(start, end) character offsets of each C# block's body, outermost only."""
        out = []
        pos = 0
        while True:
            m = CODE_BLOCK.search(text, pos)
            if not m:
                return out
            brace = m.end() - 1
            end = _close(text, brace)
            out.append((brace + 1, end))
            pos = end + 1

    def analyze_file(self, file_path: Path, project_root: Path) -> List[CodeElement]:
        from .treesitter import extract_elements

        if not self.available():
            return []
        try:
            text = Path(file_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
        rel = Path(file_path).relative_to(project_root).as_posix()
        component = Path(file_path).stem
        blocks = self.blocks(text)
        markup = text
        for start, end in reversed(blocks):  # markup only, for the reference scan
            markup = markup[:start] + " " * (end - start) + markup[end:]

        lines_total = text.count("\n") + 1
        cls = CodeElement(name=component, element_type="class", file=rel, line=1, signature=f"component {component}",
                          simple_name=component)
        cls.end_line = lines_total
        cls.is_test = False
        elements = [cls]

        for name in markup_references(markup):
            cls.calls.append(name)
            cls.call_sites.append(("", name))

        for start, end in blocks:
            first_line = text.count("\n", 0, start) + 1
            wrapped = ("class __Razor {" + text[start:end] + "\n}").encode("utf-8")
            for el in extract_elements(self.csharp, wrapped, rel):
                if el.element_type == "class" and el.simple_name == "__Razor":
                    for call in el.calls:
                        if call not in cls.calls:
                            cls.calls.append(call)
                    for site in el.call_sites:
                        if site not in cls.call_sites:
                            cls.call_sites.append(site)
                    cls.member_calls = sorted(set(cls.member_calls) | set(el.member_calls))
                    continue
                el.line = first_line + el.line - 1
                if el.end_line:
                    el.end_line = first_line + el.end_line - 1
                if el.class_name == "__Razor":
                    el.class_name = component
                    el.name = f"{component}.{el.simple_name}"
                elif el.name.startswith("__Razor."):
                    el.name = component + el.name[len("__Razor"):]
                el.is_test = False
                elements.append(el)
        return elements

    def generate_anchor_pattern(self, element: CodeElement) -> AnchorPattern:
        if element.element_type == "class":
            return AnchorPattern(pattern=r"(?s)\A", is_regex=True, description=f"Component: {element.name}")
        return self.csharp.generate_anchor_pattern(element)

    def is_test_file(self, rel_path: str) -> bool:
        return False

    @property
    def implicit_self(self) -> bool:
        return True
