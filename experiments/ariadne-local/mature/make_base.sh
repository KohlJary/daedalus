#!/bin/sh
# Rebuild base/ (the repo snapshot the mature tasks run against) from the recorded commit.
cd "$(dirname "$0")" && rm -rf base && mkdir base && git -C ../../.. archive "$(cat BASE_COMMIT)" | tar -x -C base
