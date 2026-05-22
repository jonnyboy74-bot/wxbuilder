#!/bin/bash
# Restart server so code changes (e.g. Export Team Brief) are always loaded.
cd "$(dirname "$0")"
exec python3 weather_brief_server.py
