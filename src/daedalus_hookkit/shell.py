"""
Shell command lines as hooks see them: the commands a Bash call runs, split the way a shell would.

`parse(line)` returns every command the line would run, each with its VAR=value assignments, its words,
and the bodies of its heredocs. It handles:
- && || ; | & and newlines outside quotes; line continuations;
- quotes (a quoted `&&` or `gh pr merge` is text, not a command);
- heredoc bodies, read line by line: text for most commands, but commands for `bash <<EOF` / `sh <<EOF`;
- command substitutions $(...) and `...`, whose contents are commands too;
- lead-in keywords (then, do, else, !, {, (, if, while, until, time) and wrappers (env, sudo, nohup,
  exec, command, nice, timeout N), so `...; then gh pr merge 5; fi` runs `gh pr merge 5`;
- `bash -c '...'`, `sh -c '...'` and `eval '...'`, whose argument is parsed as commands.
`cd` commands and `for`/`case` headers are left out. A path to a command is reduced to its name.
It is a reader for hooks, not a shell: anything it can't parse is split on whitespace rather than raised.
"""

import re

ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
OPERATORS = {"&&", "||", ";", "|", "&", ";;", "|&"}
HEREDOC_START = re.compile(r"<<(?!<)-?[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
LEAD = {"then", "do", "else", "elif", "!", "{", "(", "if", "while", "until", "time", "}", ")"}
WRAPPERS = {"env", "sudo", "nohup", "exec", "command", "nice", "builtin", "stdbuf"}
HEADERS = {"for", "case", "select", "function", "done", "fi", "esac"}
SHELLS = {"bash", "sh", "zsh", "dash"}
MAX_DEPTH = 4


class Cmd:
    """One command: env (its VAR=value words), words, heredocs (bodies of its << redirections, in order)
    and substs ({"SUBSTn": commands} for each $(...) or `...` among its words)."""

    __slots__ = ("env", "words", "heredocs", "substs")

    def __init__(self, env: dict, words: list, heredocs: list, substs: dict = None):
        self.env, self.words, self.heredocs, self.substs = env, words, heredocs, substs or {}

    def __repr__(self) -> str:
        return f"Cmd({self.env!r}, {self.words!r}, {self.heredocs!r})"


def commands(line: str) -> list:
    """Each command's words (see `parse` for its assignments and heredoc bodies)."""
    return [c.words for c in parse(line)]


def parse(line: str, depth: int = 0, bodies: list = None) -> list:
    """`bodies` is given when parsing a substitution: its heredocs were cut with the enclosing text."""
    if depth > MAX_DEPTH or not line:
        return []
    text = line.replace("\\\r\n", "").replace("\\\n", "")
    if bodies is None:
        text, bodies = _cut_heredocs(text)
    text, inner = _cut_substitutions(text)
    out: list = []
    nested = {}
    for n, body in enumerate(inner):
        nested[f"SUBST{n}"] = parse(body, depth + 1, bodies)
        out += nested[f"SUBST{n}"]
    for words in _split(_newlines_to_semicolons(text)):
        cmd = _clean(words, bodies)
        if cmd is None:
            continue
        cmd.substs = {k: v for k, v in nested.items() if any(k in w for w in cmd.words)}
        out.append(cmd)
        out += _nested(cmd, depth)
    return out


def _cut_heredocs(text: str) -> tuple:
    """Remove heredoc bodies, reading line by line; return the text and the bodies in order."""
    lines = text.split("\n")
    kept, bodies, i = [], [], 0
    while i < len(lines):
        ln = lines[i]
        kept.append(ln)
        i += 1
        for m in HEREDOC_START.finditer(_outside_single_quotes(ln)):
            strip_tabs = ln.startswith("<<-", m.start())
            delim, body = m.group(2), []
            while i < len(lines):
                cur = lines[i]
                i += 1
                if (cur.lstrip("\t") if strip_tabs else cur).strip() == delim:
                    break
                body.append(cur)
            bodies.append("\n".join(body))
    return "\n".join(kept), bodies


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


def _cut_substitutions(text: str) -> tuple:
    """Replace $(...) and `...` outside single quotes with a placeholder word; return their contents."""
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
        if text.startswith("$(", i) and not text.startswith("$((", i):
            depth, j = 1, i + 2
            while j < len(text) and depth:
                depth += {"(": 1, ")": -1}.get(text[j], 0)
                j += 1
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
    """Each command's raw words; operators and parentheses end a command."""
    out, words = [], []
    for tok in _tokens(text) + [";"]:
        if tok in OPERATORS or (tok and set(tok) <= set(";&|")) or tok in ("(", ")"):
            if words:
                out.append(words)
            words = []
        else:
            words.append(tok)
    return out


def _clean(words: list, bodies: list):
    """Strip lead-in keywords, assignments and wrappers; attach this command's heredoc bodies (consumed in
    order, one per `<<` it carries). None for commands that are no command (cd, headers, empty)."""
    env: dict = {}
    words = list(words)
    changed = True
    while words and changed:
        changed = False
        w = words[0]
        if w in LEAD:
            words, changed = words[1:], True
        elif ASSIGNMENT.match(w):
            k, _, v = w.partition("=")
            env[k] = v
            words, changed = words[1:], True
        elif w.rsplit("/", 1)[-1] in WRAPPERS:
            name = w.rsplit("/", 1)[-1]
            words, changed = words[1:], True
            while words and words[0].startswith("-") and name != "env":
                words = words[1:]
                if name == "sudo" and words and not words[0].startswith("-") and len(words) > 1 \
                        and words[0] not in ("gh", "git") and not words[1].startswith("-"):
                    words = words[1:]  # sudo -u USER
        elif w == "timeout":
            words = words[1:]
            while words and (words[0].startswith("-") or re.match(r"^\d+(\.\d+)?[smhd]?$", words[0])):
                words = words[1:]
            changed = True
    mine = []
    for w in words:
        for _ in range(w.count("<<") - 2 * w.count("<<<")):
            if bodies:
                mine.append(bodies.pop(0))
    if not words or words[0] == "cd" or words[0] in HEADERS:
        return None
    words[0] = words[0].rsplit("/", 1)[-1]
    return Cmd(env, words, mine)


def _nested(cmd: Cmd, depth: int) -> list:
    """Commands run by `bash -c`, `eval`, or a shell fed a heredoc."""
    w = cmd.words
    if w[0] in SHELLS:
        if "-c" in w[1:]:
            i = w.index("-c")
            return parse(w[i + 1], depth + 1) if i + 1 < len(w) else []
        if all(x.startswith("-") or x.startswith("<<") for x in w[1:]):
            return [c for body in cmd.heredocs for c in parse(body, depth + 1)]
    if w[0] == "eval":
        return parse(" ".join(w[1:]), depth + 1)
    return []
