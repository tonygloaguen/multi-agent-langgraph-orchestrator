#!/usr/bin/env bash
if command -v rtk >/dev/null 2>&1; then
    rtk compress
else
    cat
fi
