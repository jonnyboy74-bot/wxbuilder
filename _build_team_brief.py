#!/usr/bin/env python3
"""CLI wrapper — prefer Export Team Brief in WXBuilder; this rebuilds from live GRIBs only."""
import json
import sys
from export_team_brief import TeamBriefExportError, export_team_brief

# Legacy standalone builder: fetch GRIBs and synthesize minimal briefing.
# For production use, export from the app UI (POST /api/export-team-brief).

if __name__ == "__main__":
    print("Use Export Team Brief in WXBuilder to snapshot current app state.")
    print("This CLI is deprecated; run export_team_brief.py only via the server API.")
    sys.exit(1)
