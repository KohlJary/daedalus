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
COMPONENT_TAG = re.compile(r"<([A-Z]\w*)(?=[\s/>])")
HANDLER = re.compile(r"@(?:on\w+|bind\w*(?::\w+)?)\s*=\s*\"\s*(?:\(\)\s*=>\s*)?@?([A-Za-z_]\w*)")
EXPRESSION_CALL = re.compile(r"@\(?\s*([A-Za-z_]\w*)\s*\(")
RAZOR_KEYWORDS = {"if", "foreach", "for", "while", "switch", "using", "code", "functions", "page", "inject",
                  "model", "inherits", "implements", "layout", "attribute", "typeparam", "namespace", "await",
                  "section", "RenderBody", "RenderSection", "Html", "Url", "nameof", "typeof"}


def _close(text: str, open_at: int) -> int:
    """Index of the brace closing the one at open_at (strings and comments are not special-cased)."""
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return len(text) - 1


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

        refs = set(COMPONENT_TAG.findall(markup)) | set(HANDLER.findall(markup)) | set(EXPRESSION_CALL.findall(markup))
        refs -= RAZOR_KEYWORDS
        for name in sorted(refs):
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
