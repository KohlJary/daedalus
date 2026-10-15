"""
Shell command lines as hooks see them: the commands a Bash call runs, split the way a shell would.

`parse(line)` returns every command the line would run, each with its VAR=value assignments, its words,
the bodies of its heredocs, and the commands of its substitutions. It handles:
- && || ; | & |& and newlines outside quotes; line continuations; comments (`# ...`, quote-aware);
- quotes (a quoted `&&` or `gh pr merge` is text, not a command);
- heredocs (<<WORD, <<'WORD', <<-WORD, delimiters like END-X), cut line by line and attached to the
  command that has the << by position; `<<<` herestrings are not heredocs. The body of an unquoted
  heredoc still runs its $(...) substitutions;
- command substitutions $(...) and `...`, whose contents are commands; arithmetic $((...)) and ((...));
- lead-in keywords (then, do, else, !, {, (, if, while, until, time), leading redirections
  (2>/dev/null, > f) and wrappers with their options (env -i -u X, sudo -u U, nice -n N, timeout 20,
  nohup, exec, command, stdbuf), so `...; then gh pr merge 5; fi` runs `gh pr merge 5`;
- shells given a script: `bash -c '...'` (and clusters like -lc, -ec), `eval '...'`, `bash <<EOF`,
  `bash <<< '...'`, and `echo '...' | bash`.
`cd` commands and `for`/`case`/`function` headers are left out. A path to a command becomes its name.
It is a reader for hooks, not a shell: anything it can't parse is split on whitespace rather than raised.
"""

import re

ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
OPERATORS = {"&&", "||", ";", "|", "&", ";;", "|&", ";&", ";;&"}
# a heredoc start, not a herestring: <<WORD, << 'WORD', <<-"WORD"
HEREDOC_START = re.compile(r"(?<!<)<<(?!<)(-?)[ \t]*(['\"]?)([^\s'\"<>;&|()]+)\2")
HEREDOC_MARK = re.compile(r"<<HEREDOC(\d+)\b")
REDIRECT = re.compile(r"^(\d*|&)(>>?|<|>&|<&|&>>?)(\S*)$")
LEAD = {"then", "do", "else", "elif", "!", "{", "(", "if", "while", "until", "time", "}", ")", "((", "))"}
WRAPPER_ARGS = {  # wrappers and the options of theirs that take a value
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
    "sudo": {"-u", "-g", "-h", "-p", "-C", "-D", "-R", "-T", "-U"},
    "nice": {"-n", "--adjustment"},
    "stdbuf": {"-i", "-o", "-e"},
    "exec": {"-a"},
    "nohup": set(), "command": set(), "builtin": set(),
}
HEADERS = {"for", "case", "select", "function", "done", "fi", "esac"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
FEEDERS = {"echo", "printf"}
MAX_DEPTH = 4


class Cmd:
    """One command: env (its VAR=value words), words, heredocs (bodies of its << redirections, in order)
    and substs ({"SUBSTn": commands} for each $(...) or `...` among its words)."""

    __slots__ = ("env", "words", "heredocs", "substs", "piped")

    def __init__(self, env: dict, words: list, heredocs: list, substs: dict = None):
        self.env, self.words, self.heredocs, self.substs = env, words, heredocs, substs or {}
        self.piped = False  # its input is the previous command's output

    def __repr__(self) -> str:
        return f"Cmd({self.env!r}, {self.words!r}, {self.heredocs!r})"


def commands(line: str) -> list:
    """Each command's words (see `parse` for its assignments, heredoc bodies and substitutions)."""
    return [c.words for c in parse(line)]


def parse(line: str, depth: int = 0, bodies: list = None) -> list:
    """`bodies` is given when parsing a substitution: its heredocs were cut with the enclosing text, and
    its <<HEREDOCn marks index into that list."""
    if depth > MAX_DEPTH or not line:
        return []
    text = line.replace("\\\r\n", "").replace("\\\n", "")
    extra: list = []
    if bodies is None:
        text, bodies, unquoted = _cut_heredocs(text)
        for n in unquoted:  # an unquoted heredoc's body still expands $(...)
            _, inner = _cut_substitutions(bodies[n])
            for body in inner:
                extra += parse(body, depth + 1, bodies)
    text, inner = _cut_substitutions(text)
    out: list = []
    nested = {}
    for n, body in enumerate(inner):
        nested[f"SUBST{n}"] = parse(body, depth + 1, bodies)
        out += nested[f"SUBST{n}"]
    prev = None
    for words, piped in _split(_newlines_to_semicolons(text)):
        cmd = _clean(words, bodies)
        if cmd is None:
            prev = None
            continue
        cmd.piped = piped
        cmd.substs = {k: v for k, v in nested.items() if any(k in w for w in cmd.words)}
        out.append(cmd)
        out += _nested(cmd, prev, depth, bodies)
        prev = cmd
    return out + extra


def _cut_heredocs(text: str) -> tuple:
    """Strip comments and cut heredoc bodies, line by line. Each heredoc start becomes <<HEREDOCn, n
    indexing the returned bodies, so bodies attach to their command by position. Returns (text,
    bodies, indexes of unquoted heredocs)."""
    lines = text.split("\n")
    kept, bodies, unquoted, i, quote = [], [], [], 0, ""
    while i < len(lines):
        ln, quote = _strip_comment(lines[i], quote)
        i += 1
        starts = list(HEREDOC_START.finditer(_outside_single_quotes(ln))) if not quote or quote == '"' else []
        pieces, last = [], 0
        for m in starts:
            n = len(bodies)
            strip_tabs, delim = m.group(1) == "-", m.group(3)
            body = []
            while i < len(lines):
                cur = lines[i]
                i += 1
                if (cur.lstrip("\t") if strip_tabs else cur).strip() == delim:
                    break
                body.append(cur)
            bodies.append("\n".join(body))
            if not m.group(2):
                unquoted.append(n)
            pieces += [ln[last:m.start()], f"<<HEREDOC{n}"]
            last = m.end()
        kept.append("".join(pieces) + ln[last:])
    return "\n".join(kept), bodies, unquoted


def _strip_comment(line: str, quote: str) -> tuple:
    """The line without a trailing `# comment` (a # starting a word, outside quotes), and the quote still
    open at its end (a quoted string may span lines)."""
    escaped = False
    for i, ch in enumerate(line):
        if escaped:
            escaped = False
        elif ch == "\\" and quote != "'":
            escaped = True
        elif quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t;&|()"):
            return line[:i], quote
    return line, quote


def _outside_single_quotes(line: str) -> str:
    """The line with single-quoted spans blanked (same length), except a quoted heredoc delimiter
    (<<'EOF'). A `<<` inside double quotes still starts a heredoc: that is the usual
    `git commit -m "$(cat <<'EOF' ... )"` form."""
    out, quoted, keep = [], False, False
    for i, ch in enumerate(line):
        if ch == "'" and not quoted:
            quoted, keep = True, line[:i].rstrip(" \t").endswith(("<<", "<<-"))
            out.append(ch)
        elif ch == "'" and quoted:
            quoted = False
            out.append(ch)
        else:
            out.append(ch if (not quoted or keep) else " ")
    return "".join(out)


def _matching(text: str, i: int, opener: str = "(", closer: str = ")") -> int:
    """The index just past the closer matching the opener at text[i] (end of text when unbalanced)."""
    depth, j = 0, i
    while j < len(text):
        if text[j] == opener:
            depth += 1
        elif text[j] == closer:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return len(text)


def _cut_substitutions(text: str) -> tuple:
    """Replace $(...) and `...` outside single quotes with SUBSTn words and return their contents;
    arithmetic $((...)) and ((...)) become a plain word."""
    out, inner, i, quote = [], [], 0, ""
    while i < len(text):
        ch = text[i]
        if quote == "'":
            out.append(ch)
            if ch == "'":
                quote = ""
            i += 1
            continue
        if ch == "\\" and i + 1 < len(text):
            out.append(text[i:i + 2])
            i += 2
            continue
        if text.startswith("$((", i):
            out.append("ARITH")
            i = _matching(text, i + 1)
            continue
        if text.startswith("((", i) and not quote and (i == 0 or text[i - 1] in " \t;&|\n"):
            out.append(":")
            i = _matching(text, i)
            continue
        if text.startswith("$(", i):
            j = _matching(text, i + 1)
            out.append(f"SUBST{len(inner)}")
            inner.append(text[i + 2:j - 1])
            i = j
            continue
        if ch == "`":
            j = text.find("`", i + 1)
            j = len(text) if j < 0 else j
            out.append(f"SUBST{len(inner)}")
            inner.append(text[i + 1:j])
            i = j + 1
            continue
        if ch == "'" and quote != '"':
            quote = "'"
        elif ch == '"':
            quote = "" if quote == '"' else '"'
        out.append(ch)
        i += 1
    return "".join(out), inner


def _newlines_to_semicolons(text: str) -> str:
    out, quote, escaped = [], "", False
    for ch in text:
        if escaped:
            escaped = False
        elif ch == "\\" and quote != "'":
            escaped = True
        elif quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "\n":
            ch = ";"
        out.append(ch)
    return "".join(out)


def _tokens(text: str) -> list:
    import shlex

    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|()")
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return [t for part in re.split(r"(&&|\|\||;|\||\(|\))", text) for t in (part.split() or [part]) if t]


def _split(text: str) -> list:
    """[(words, piped)] per command; operators and parentheses end a command. A run of punctuation that
    shlex grouped (`));`, `;;&`) splits like its parts."""
    out, words, piped, next_piped = [], [], False, False
    for tok in _tokens(text) + [";"]:
        if tok and set(tok) <= set(";&|()"):
            if words:
                out.append((words, piped))
            words = []
            piped = next_piped = tok.endswith("|") and not tok.endswith("||")
            continue
        if not words:
            piped = next_piped
        words.append(tok)
    return out


def _clean(words: list, bodies: list):
    """Strip lead-in keywords, leading redirections, assignments and wrappers; attach this command's
    heredoc bodies. None for commands that are no command (cd, headers, empty)."""
    env: dict = {}
    words = list(words)
    changed = True
    while words and changed:
        changed = False
        w = words[0]
        name = w.rsplit("/", 1)[-1]
        redirect = REDIRECT.match(w)
        if w in LEAD:
            words, changed = words[1:], True
        elif redirect and not w.startswith("<<"):
            words = words[1:] if redirect.group(3) else words[2:]  # `2>/dev/null` or `> file`
            changed = True
        elif ASSIGNMENT.match(w):
            k, _, v = w.partition("=")
            env[k] = v
            words, changed = words[1:], True
        elif name in WRAPPER_ARGS:
            takes = WRAPPER_ARGS[name]
            words, changed = words[1:], True
            while words and words[0].startswith("-") and words[0] != "-":
                opt = words[0]
                words = words[2:] if opt in takes else words[1:]
                if opt == "--":
                    break
            if name == "env":
                while words and ASSIGNMENT.match(words[0]):
                    k, _, v = words[0].partition("=")
                    env[k] = v
                    words = words[1:]
        elif w == "timeout":
            words = words[1:]
            while words and (words[0].startswith("-") or re.match(r"^\d+(\.\d+)?[smhd]?$", words[0])):
                words = words[2:] if words[0] in ("-s", "--signal", "-k", "--kill-after") else words[1:]
            changed = True
    if not words or words[0] == "cd" or words[0] in HEADERS or words[0].endswith("()"):
        return None
    mine = [bodies[int(m.group(1))] for w in words for m in HEREDOC_MARK.finditer(w)
            if int(m.group(1)) < len(bodies)]
    words = [w if not HEREDOC_MARK.fullmatch(w) else "<<" for w in words]
    words[0] = words[0].rsplit("/", 1)[-1]
    return Cmd(env, words, mine)


def _script_arg(words: list):
    """The script a shell runs with -c (also in clusters such as -lc, -ec), or None."""
    for i, w in enumerate(words[1:], 1):
        if w.startswith("-") and not w.startswith("--") and "c" in w[1:]:
            return words[i + 1] if i + 1 < len(words) else ""
        if not w.startswith("-"):
            return None
    return None


def _nested(cmd: Cmd, prev, depth: int, bodies: list) -> list:
    """Commands a shell runs from its argument, heredoc, herestring or pipe; eval's argument."""
    w = cmd.words
    if w[0] in SHELLS:
        script = _script_arg(w)
        if script is not None:
            return parse(script, depth + 1)
        if "<<<" in w and w.index("<<<") + 1 < len(w):
            return parse(w[w.index("<<<") + 1], depth + 1)
        out = [c for body in cmd.heredocs for c in parse(body, depth + 1)]
        if cmd.piped and prev is not None:
            if prev.words[0] in FEEDERS:
                out += parse(" ".join(x for x in prev.words[1:] if not x.startswith("-")), depth + 1)
            out += [c for body in prev.heredocs for c in parse(body, depth + 1)]
        return out
    if w[0] == "eval":
        return parse(" ".join(w[1:]), depth + 1)
    return []
