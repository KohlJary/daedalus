"""
Language Support for Mind Palace Cartographer.

Provides language-specific code analysis and anchor pattern generation.
Each language implementation knows how to:
1. Parse source files and extract code elements
2. Generate anchor patterns that match actual code syntax
3. Verify anchors exist in source files
"""

import ast
import hashlib
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Type

logger = logging.getLogger(__name__)


@dataclass
class CodeElement:
    """A discovered code element (function, class, etc.)."""
    name: str
    element_type: str  # "function", "class", "method"
    file: str
    line: int
    signature: str
    docstring: Optional[str] = None
    calls: List[str] = field(default_factory=list)
    called_by: List[str] = field(default_factory=list)
    parameters: List[Tuple[str, str]] = field(default_factory=list)
    returns: Optional[str] = None
    # For methods, store class info separately
    class_name: Optional[str] = None
    # The simple name without class prefix
    simple_name: Optional[str] = None
    # Last line of the definition, when the analyzer knows it
    end_line: Optional[int] = None
    # Names called through an object (`obj.name()`), a subset of calls
    member_calls: List[str] = field(default_factory=list)
    # Set by analyzers that know their language's test conventions; None means "use the Python rule"
    is_test: Optional[bool] = None
    # Each call as (qualifier, name): "" for a plain call, an identifier for `mod.name()` / `Foo.name()`,
    # "self" for self/this, "?" for anything more complex. Used to resolve calls through imports.
    call_sites: List[Tuple[str, str]] = field(default_factory=list)

    def __post_init__(self):
        # Derive simple_name from name if not set
        if self.simple_name is None:
            if "." in self.name and self.element_type == "method":
                self.simple_name = self.name.split(".")[-1]
            else:
                self.simple_name = self.name


@dataclass
class AnchorPattern:
    """Pattern for locating code in source files."""
    pattern: str
    is_regex: bool = False
    # For display purposes
    description: str = ""

    def matches(self, content: str) -> bool:
        """Check if this pattern matches the content."""
        if self.is_regex:
            return bool(re.search(self.pattern, content, re.MULTILINE))
        return self.pattern in content

    def find_line(self, content: str) -> Optional[int]:
        """Find the line number where this pattern matches (1-indexed)."""
        lines = content.split("\n")
        if self.is_regex:
            regex = re.compile(self.pattern)
            for i, line in enumerate(lines, 1):
                if regex.search(line):
                    return i
        else:
            for i, line in enumerate(lines, 1):
                if self.pattern in line:
                    return i
        return None


class LanguageSupport(ABC):
    """
    Base class for language-specific code analysis.

    Subclasses implement parsing and pattern generation for specific languages.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable language name."""
        pass

    @property
    @abstractmethod
    def extensions(self) -> List[str]:
        """File extensions this language handles (e.g., ['.py', '.pyi'])."""
        pass

    @abstractmethod
    def analyze_file(self, file_path: Path, project_root: Path) -> List[CodeElement]:
        """
        Analyze a source file and extract code elements.

        Args:
            file_path: Absolute path to the source file
            project_root: Project root for computing relative paths

        Returns:
            List of discovered code elements
        """
        pass

    @abstractmethod
    def generate_anchor_pattern(self, element: CodeElement) -> AnchorPattern:
        """
        Generate an anchor pattern for locating this element in source.

        Args:
            element: The code element to create an anchor for

        Returns:
            AnchorPattern that can locate this element
        """
        pass

    def is_test_file(self, rel_path: str) -> bool:
        """Whether a repo-relative path is test code."""
        return False

    def test_file_candidates(self, rel_path: str) -> List[str]:
        """Conventional test files for a source file (they may not exist)."""
        return []

    def constructor_of(self, class_name: str) -> Tuple[str, ...]:
        """Method names that construction of `class_name` runs."""
        return ()

    # Files that stand for their directory (a package's __init__.py, index.ts, mod.rs)
    package_markers: Tuple[str, ...] = ()

    def module_doc(self, file_path: Path) -> Optional[str]:
        """The file's leading documentation (a module docstring, a leading comment block)."""
        return None

    def is_private_file(self, file_name: str) -> bool:
        """Files the palace builder doesn't map as buildings (Python's _private.py modules)."""
        return False

    def file_imports(self, file_path: Path, project_root: Path) -> Dict[str, Tuple[str, Optional[str]]]:
        """Names the file binds by importing: local name -> (module spec, imported symbol or None for a whole
        module). Specs are tagged by kind ("py:a.b", "js:src/cart", "go:example.com/m/pkg",
        "java:com/x/Foo", "ext:" for anything outside the project); query.py resolves them."""
        return {}

    @property
    def implicit_self(self) -> bool:
        """Whether a plain `name()` call can reach a method of the enclosing class (Java, Ruby) or only
        functions (Go, JavaScript). The Python query graph keeps its measured behaviour either way."""
        return True

    def compute_signature_hash(self, element: CodeElement) -> str:
        """Compute a hash of the element's signature for drift detection."""
        return hashlib.md5(element.signature.encode()).hexdigest()[:8]


class PythonSupport(LanguageSupport):
    """Python language support for the Cartographer."""

    @property
    def name(self) -> str:
        return "Python"

    @property
    def extensions(self) -> List[str]:
        return [".py", ".pyi"]

    def is_test_file(self, rel_path: str) -> bool:
        name = Path(rel_path).name
        return (rel_path.startswith("tests/") or "/tests/" in rel_path or name.startswith("test_")
                or name.endswith("_test.py") or name == "conftest.py")

    def test_file_candidates(self, rel_path: str) -> List[str]:
        return [str(Path("tests") / f"test_{Path(rel_path).stem}.py")]

    package_markers = ("__init__.py",)

    def module_doc(self, file_path: Path) -> Optional[str]:
        try:
            return ast.get_docstring(ast.parse(Path(file_path).read_text(encoding="utf-8")))
        except (SyntaxError, UnicodeDecodeError, OSError, ValueError):
            return None

    def is_private_file(self, file_name: str) -> bool:
        return file_name.startswith("_") and file_name != "__init__.py"

    def file_imports(self, file_path: Path, project_root: Path) -> Dict[str, Tuple[str, Optional[str]]]:
        try:
            tree = self._parse(file_path)
        except (SyntaxError, UnicodeDecodeError, OSError, ValueError):
            return {}
        rel = Path(file_path).relative_to(project_root)
        package = list(rel.parent.parts)  # relative imports resolve against the file's directory
        out: Dict[str, Tuple[str, Optional[str]]] = {}

        def bind(name: str, target: Tuple[str, Optional[str]]) -> None:
            # A name imported twice from different places (try/except fallbacks, a function-local import)
            # can't be decided statically
            out[name] = target if out.get(name, target) == target else ("ambiguous:", None)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        bind(alias.asname, (f"py:{alias.name}", None))
                    else:  # `import a.b` binds `a`
                        head = alias.name.split(".")[0]
                        bind(head, (f"py:{head}", None))
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    parts = package[: len(package) - (node.level - 1)] if node.level > 1 else list(package)
                    if node.level - 1 > len(package):
                        continue
                    base = ".".join(parts + ([node.module] if node.module else []))
                else:
                    base = node.module or ""
                for alias in node.names:
                    if alias.name != "*":
                        bind(alias.asname or alias.name, (f"py:{base}", alias.name))
        return out

    def constructor_of(self, class_name: str) -> Tuple[str, ...]:
        return ("__init__",)

    _last_parse: Optional[Tuple[object, ast.AST]] = None

    def _parse(self, file_path: Path) -> ast.AST:
        """Parse, reusing the last tree for the same unchanged file (analysis then imports)."""
        st = Path(file_path).stat()
        key = (str(file_path), st.st_mtime_ns, st.st_size)
        if self._last_parse is not None and self._last_parse[0] == key:
            return self._last_parse[1]
        with open(file_path) as f:
            tree = ast.parse(f.read())
        self._last_parse = (key, tree)
        return tree

    def analyze_file(self, file_path: Path, project_root: Path) -> List[CodeElement]:
        """Analyze a Python file using AST parsing."""
        elements = []

        try:
            tree = self._parse(file_path)
            source = ""
        except Exception as e:
            logger.warning(f"Failed to parse {file_path}: {e}")
            return elements

        relative_path = str(file_path.relative_to(project_root))

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Skip methods - they're handled with their classes
                # Check if this function is at module level
                # (ast.walk doesn't preserve hierarchy, so we check later)
                pass

            elif isinstance(node, ast.ClassDef):
                # Extract class
                element = self._extract_class(node, relative_path, source)
                elements.append(element)

                # Extract methods from this class
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method = self._extract_function(
                            item, relative_path, source,
                            class_name=node.name
                        )
                        elements.append(method)

        # Extract top-level functions (need a second pass to avoid class methods)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                element = self._extract_function(node, relative_path, source)
                elements.append(element)

        return elements

    def _extract_function(
        self,
        node: ast.FunctionDef,
        file_path: str,
        source: str,
        class_name: Optional[str] = None,
    ) -> CodeElement:
        """Extract a function/method as a CodeElement."""
        # Build argument list
        args = []
        for arg in node.args.args:
            arg_type = ""
            if arg.annotation:
                arg_type = ast.unparse(arg.annotation)
            args.append((arg.arg, arg_type))

        # Get return type
        returns = None
        if node.returns:
            returns = ast.unparse(node.returns)

        # Build signature
        signature = f"def {node.name}({', '.join(a[0] for a in args)})"
        if returns:
            signature += f" -> {returns}"

        # Get docstring
        docstring = ast.get_docstring(node)
        member_calls = sorted({c.func.attr for c in ast.walk(node)
                               if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)})
        call_sites = _python_call_sites(node)

        # Find function calls within this function
        calls = []
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    calls.append(child.func.id)
                elif isinstance(child.func, ast.Attribute):
                    calls.append(child.func.attr)

        element_type = "method" if class_name else "function"
        full_name = f"{class_name}.{node.name}" if class_name else node.name

        return CodeElement(
            name=full_name,
            element_type=element_type,
            file=file_path,
            line=node.lineno,
            signature=signature,
            docstring=docstring,
            calls=list(set(calls)),
            parameters=args,
            returns=returns,
            class_name=class_name,
            simple_name=node.name,
            end_line=node.end_lineno,
            member_calls=member_calls,
            call_sites=call_sites,
        )

    def _extract_class(self, node: ast.ClassDef, file_path: str, source: str) -> CodeElement:
        """Extract a class as a CodeElement."""
        # Get base classes
        bases = [ast.unparse(b) for b in node.bases]
        signature = f"class {node.name}"
        if bases:
            signature += f"({', '.join(bases)})"

        docstring = ast.get_docstring(node)

        return CodeElement(
            name=node.name,
            element_type="class",
            file=file_path,
            line=node.lineno,
            signature=signature,
            docstring=docstring,
            simple_name=node.name,
            end_line=node.end_lineno,
            member_calls=sorted({c.func.attr for c in ast.walk(node)
                                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}),
            call_sites=_python_call_sites(node),
        )

    def generate_anchor_pattern(self, element: CodeElement) -> AnchorPattern:
        """
        Generate Python-appropriate anchor patterns.

        Patterns:
        - Functions: "def function_name(" (literal)
        - Classes: "class ClassName" (literal, handles inheritance variations)
        - Methods: regex to match "def method_name(" with leading whitespace
        """
        if element.element_type == "class":
            # Classes: match "class Name" - handles "(bases)" and ":" variations
            return AnchorPattern(
                pattern=f"class {element.simple_name}",
                is_regex=False,
                description=f"Class definition: {element.simple_name}",
            )

        elif element.element_type == "method":
            # Methods: need regex to handle indentation and async
            # Match "def method_name(" or "async def method_name(" with leading whitespace
            # Using simple_name to avoid "ClassName.method_name"
            pattern = rf"^\s+(?:async\s+)?def {re.escape(element.simple_name)}\("
            return AnchorPattern(
                pattern=pattern,
                is_regex=True,
                description=f"Method: {element.class_name}.{element.simple_name}",
            )

        else:  # function
            # Top-level functions: handle both sync and async
            # "def name(" or "async def name(" at start of line
            pattern = rf"^(?:async\s+)?def {re.escape(element.simple_name)}\("
            return AnchorPattern(
                pattern=pattern,
                is_regex=True,
                description=f"Function: {element.simple_name}",
            )


def _python_call_sites(node) -> List[Tuple[str, str]]:
    sites = set()
    for c in ast.walk(node):
        if not isinstance(c, ast.Call):
            continue
        if isinstance(c.func, ast.Name):
            sites.add(("", c.func.id))
        elif isinstance(c.func, ast.Attribute):
            value = c.func.value
            qualifier = ("self" if value.id in ("self", "cls") else value.id) if isinstance(value, ast.Name) else "?"
            sites.add((qualifier, c.func.attr))
    return sorted(sites)


class TypeScriptSupport(LanguageSupport):
    """TypeScript/JavaScript language support (basic implementation)."""

    @property
    def name(self) -> str:
        return "TypeScript"

    @property
    def extensions(self) -> List[str]:
        return [".ts", ".tsx", ".js", ".jsx"]

    def analyze_file(self, file_path: Path, project_root: Path) -> List[CodeElement]:
        """
        Basic TypeScript analysis using regex patterns.

        For production use, consider using a proper TS parser like
        tree-sitter or typescript compiler API.
        """
        elements = []
        relative_path = str(file_path.relative_to(project_root))

        try:
            with open(file_path) as f:
                content = f.read()
        except Exception as e:
            logger.warning(f"Failed to read {file_path}: {e}")
            return elements

        # Function patterns
        # export function name(
        # function name(
        # const name = ( or const name = async (
        # export const name = (
        func_patterns = [
            (r"^(?:export\s+)?function\s+(\w+)\s*\(", "function"),
            (r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(", "function"),
            (r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function", "function"),
        ]

        # Class patterns
        class_pattern = r"^(?:export\s+)?class\s+(\w+)"

        # Method patterns (inside classes)
        method_patterns = [
            (r"^\s+(?:async\s+)?(\w+)\s*\([^)]*\)\s*[:{]", "method"),
            (r"^\s+(?:public|private|protected)?\s*(?:async\s+)?(\w+)\s*\(", "method"),
        ]

        lines = content.split("\n")
        current_class = None

        for lineno, line in enumerate(lines, 1):
            # Check for class
            class_match = re.match(class_pattern, line)
            if class_match:
                class_name = class_match.group(1)
                current_class = class_name
                elements.append(CodeElement(
                    name=class_name,
                    element_type="class",
                    file=relative_path,
                    line=lineno,
                    signature=f"class {class_name}",
                    simple_name=class_name,
                ))
                continue

            # Check for end of class (simplified - looks for closing brace at start)
            if current_class and re.match(r"^}", line):
                current_class = None
                continue

            # Check for functions
            for pattern, elem_type in func_patterns:
                match = re.match(pattern, line)
                if match:
                    func_name = match.group(1)
                    elements.append(CodeElement(
                        name=func_name,
                        element_type=elem_type,
                        file=relative_path,
                        line=lineno,
                        signature=f"function {func_name}()",
                        simple_name=func_name,
                    ))
                    break

            # Check for methods if inside a class
            if current_class:
                for pattern, elem_type in method_patterns:
                    match = re.match(pattern, line)
                    if match:
                        method_name = match.group(1)
                        # Skip constructor and common non-method matches
                        if method_name in ("if", "for", "while", "switch", "catch"):
                            continue
                        full_name = f"{current_class}.{method_name}"
                        elements.append(CodeElement(
                            name=full_name,
                            element_type="method",
                            file=relative_path,
                            line=lineno,
                            signature=f"{method_name}()",
                            class_name=current_class,
                            simple_name=method_name,
                        ))
                        break

        return elements

    def generate_anchor_pattern(self, element: CodeElement) -> AnchorPattern:
        """Generate TypeScript-appropriate anchor patterns."""
        if element.element_type == "class":
            return AnchorPattern(
                pattern=f"class {element.simple_name}",
                is_regex=False,
                description=f"Class: {element.simple_name}",
            )

        elif element.element_type == "method":
            # Methods can have various signatures in TS
            # Use regex to match method name followed by (
            pattern = rf"^\s+(?:async\s+)?{re.escape(element.simple_name)}\s*\("
            return AnchorPattern(
                pattern=pattern,
                is_regex=True,
                description=f"Method: {element.class_name}.{element.simple_name}",
            )

        else:  # function
            # Match various function declaration styles
            pattern = rf"(?:function\s+{re.escape(element.simple_name)}|(?:const|let|var)\s+{re.escape(element.simple_name)}\s*=)"
            return AnchorPattern(
                pattern=pattern,
                is_regex=True,
                description=f"Function: {element.simple_name}",
            )


class LanguageRegistry:
    """
    Registry of available language support implementations.

    Use this to get the appropriate language handler for a file.
    """

    def __init__(self):
        self._languages: Dict[str, LanguageSupport] = {}
        self._extension_map: Dict[str, LanguageSupport] = {}

        # Register built-in languages. With tree-sitter installed (`daedalus[palace]`), its grammars
        # take over every extension they cover, including the regex TypeScript analyzer's.
        self.register(PythonSupport())
        self.register(TypeScriptSupport())
        from .treesitter import tree_sitter_languages
        for language in tree_sitter_languages():
            # If its grammar fails to load, fall back to whatever handled these files before
            language.fallback = self._extension_map.get(language.extensions[0].lower())
            self.register(language)
        csharp = self._languages.get("c#")
        if csharp is not None:  # Razor's C# blocks parse with the C# grammar
            from .razor import RazorSupport
            self.register(RazorSupport(csharp))

    def register(self, language: LanguageSupport) -> None:
        """Register a language support implementation."""
        self._languages[language.name.lower()] = language
        for ext in language.extensions:
            self._extension_map[ext.lower()] = language

    def get_by_extension(self, file_path: Path) -> Optional[LanguageSupport]:
        """Get language support for a file based on its extension."""
        ext = file_path.suffix.lower()
        return self._extension_map.get(ext)

    def get_by_name(self, name: str) -> Optional[LanguageSupport]:
        """Get language support by language name."""
        return self._languages.get(name.lower())

    def supported_extensions(self) -> List[str]:
        """Get all supported file extensions."""
        return list(self._extension_map.keys())

    def supported_languages(self) -> List[str]:
        """Get all supported language names."""
        return list(self._languages.keys())


# Global registry instance
_registry: Optional[LanguageRegistry] = None


def get_language_registry() -> LanguageRegistry:
    """Get the global language registry."""
    global _registry
    if _registry is None:
        _registry = LanguageRegistry()
    return _registry
