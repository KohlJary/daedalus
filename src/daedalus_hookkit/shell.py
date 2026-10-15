"""Shell command lines as hooks see them: the commands a Bash call runs, split the way a shell would."""

import re

ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
OPERATORS = {"&&", "||", ";", "|", "&", ";;", "\n"}
# a heredoc: <<WORD, <<'WORD', <<"WORD" or <<-WORD, its body, and the closing WORD line
HEREDOC = re.compile(r"(<<-?[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2)([^\n]*)\n.*?\n[ \t]*\3[ \t]*(?=\n|$)", re.DOTALL)


def commands(line: str) -> list:
    """Each command in a shell line, as its words: split on && || ; | & and newlines outside quotes, with
    leading VAR=value words dropped and `cd ...` commands left out. Quoted text stays one word, so
    `git commit -m 'a && b'` is one command. An unbalanced quote falls back to whitespace splitting."""
    import shlex

    out, words = [], []
    line = _unquoted_newlines_to_semicolons(HEREDOC.sub(r"\1\4", line or ""))
    try:
        lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = [t for part in re.split(r"(&&|\|\||;|\||\n)", line or "") for t in (part.split() or [part])]
    for tok in tokens + [";"]:
        if tok in OPERATORS or (tok and set(tok) <= set(";&|")):
            while words and ASSIGNMENT.match(words[0]):
                words = words[1:]
            if words and words[0] != "cd":
                out.append(words)
            words = []
        elif tok != "\n":
            words.append(tok)
    return out


def _unquoted_newlines_to_semicolons(line: str) -> str:
    """A newline outside quotes ends a command, like `;`; inside quotes it is text."""
    out, quote, escaped = [], "", False
    for ch in line:
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
