"""
Rendering for the CLAUDE.md template: config conditionals and project-owned local slots.

Conditionals keep optional sections in or out based on template settings:

    <!-- DAEDALUS_IF sections.squash -->          kept when the setting is true
    <!-- DAEDALUS_IF git.authorship=user -->      kept when the setting equals the value
    ...
    <!-- /DAEDALUS_IF -->

Local slots are places in the managed section that belong to the project. hydrate carries their
contents over by name, so additions survive template updates:

    <!-- DAEDALUS_LOCAL breath -->
    ...project text...
    <!-- /DAEDALUS_LOCAL -->

All functions work on text with '\\n' line endings; the injector converts to the file's own.
"""

import re
from typing import Dict, List, Tuple

IF_RE = re.compile(
    r"^<!-- DAEDALUS_IF (?P<key>[a-z_.]+)(?:=(?P<value>[A-Za-z0-9_-]+))? -->\n"
    r"(?P<body>.*?)"
    r"^<!-- /DAEDALUS_IF -->\n",
    re.MULTILINE | re.DOTALL,
)

SLOT_RE = re.compile(
    r"^<!-- DAEDALUS_LOCAL (?P<name>[a-z0-9-]+) -->\n"
    r"(?P<body>.*?)"
    r"^<!-- /DAEDALUS_LOCAL -->\n",
    re.MULTILINE | re.DOTALL,
)

# Slot that receives the contents of slots the new template no longer has
FALLBACK_SLOT = "end"


class TemplateError(ValueError):
    """The template refers to a setting that doesn't exist, or is malformed."""


def flatten(settings: dict, prefix: str = "") -> Dict[str, object]:
    """{'git': {'authorship': 'user'}} -> {'git.authorship': 'user'}"""
    flat = {}
    for key, value in settings.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(flatten(value, name + "."))
        else:
            flat[name] = value
    return flat


def render_conditionals(text: str, settings: dict) -> str:
    """Keep or drop each DAEDALUS_IF block. Unknown keys raise TemplateError rather than read as false."""
    flat = flatten(settings)

    def replace(m: re.Match) -> str:
        key, expected = m.group("key"), m.group("value")
        if key not in flat:
            raise TemplateError(f"template condition uses unknown setting '{key}'")
        actual = flat[key]
        keep = str(actual) == expected if expected is not None else bool(actual)
        return m.group("body") if keep else ""

    rendered = IF_RE.sub(replace, text)
    if "DAEDALUS_IF" in rendered:
        raise TemplateError("unbalanced or nested DAEDALUS_IF block (nesting isn't supported)")
    return rendered


def extract_slots(text: str) -> Dict[str, str]:
    """Slot name -> contents (between the marker lines), in file order."""
    return {m.group("name"): m.group("body") for m in SLOT_RE.finditer(text)}


def fill_slots(rendered: str, old_slots: Dict[str, str]) -> Tuple[str, List[str]]:
    """
    Put each old slot's contents into the same-named slot of the rendered template.

    Contents of a slot the template no longer has are not dropped: they go into the fallback slot
    under a comment naming the old slot. Returns the text and a list of warnings.
    """
    template_slots = set(extract_slots(rendered))
    warnings: List[str] = []
    orphans = ""

    for name, body in old_slots.items():
        if name not in template_slots and body.strip():
            orphans += f"<!-- from removed slot: {name} -->\n{body}"
            warnings.append(f"local slot '{name}' no longer exists in the template; moved its contents to '{FALLBACK_SLOT}'")

    if orphans and FALLBACK_SLOT not in template_slots:
        raise TemplateError(f"template has no '{FALLBACK_SLOT}' slot to keep removed slots' contents")

    def replace(m: re.Match) -> str:
        name = m.group("name")
        body = old_slots.get(name, "")
        if name == FALLBACK_SLOT and orphans:
            body = body + orphans
        return f"<!-- DAEDALUS_LOCAL {name} -->\n{body}<!-- /DAEDALUS_LOCAL -->\n"

    return SLOT_RE.sub(replace, rendered), warnings
