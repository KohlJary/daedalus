#!/bin/bash
# Daedalus session-start hook.
#
# `daedalus init` / `hydrate` register `daedalus hook session-start` directly in
# .claude/settings.json (edict 0007); this script is kept for setups that point
# at it. It prints the same gameplan-first brief.
exec daedalus hook session-start
