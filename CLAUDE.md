# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

See README.md for usage, commands, input file format, and data sources.

## Architecture

CLI entry point: `meshcore-tools` (defined in `[project.scripts]` in `pyproject.toml`).
Package: `src/meshcore_tools/` with a `src/` layout. Tests in `tests/`.
Dependency: `textual>=0.80` (TUI framework).

**Module layout:**
- `src/meshcore_tools/cli.py` — entry point, argparse subcommands (`nodes`, `monitor`)
- `src/meshcore_tools/letsmesh_api.py` — letsmesh HTTP client (`fetch_nodes`, `fetch_packets`)
- `src/meshcore_tools/db.py` — node database (`load_db`, `save_db`, `parse_input_file`, `update`)
- `src/meshcore_tools/nodes.py` — node query/display (`lookup`, `list_nodes`)
- `src/meshcore_tools/monitor.py` — live Textual TUI (`PacketMonitorApp`, `run_monitor`)

**Data flow:** `input/*.txt` + live API → `nodes.json` (gitignored)

**Merge logic (`update()` in db.py):** Input file nodes with partial keys (< 64 hex chars) are matched against API nodes whose full key starts with that partial. On match, the partial entry is replaced with the full 64-char key, preserving `type` and `routing` from the input file.

**API access:** Two endpoints, both require `Origin: https://analyzer.letsmesh.net` — no auth:
- `https://api.letsmesh.net/api/nodes?region=LUX` — node list
- `https://api.letsmesh.net/api/packets?region=LUX&limit=50` — recent packets (no WebSocket; poll-based)

**`nodes.json` schema per node:**
```json
{
  "name": "gw-charly",
  "type": "CLI",
  "routing": "Flood",
  "source": "sam.txt",
  "key_complete": true,
  "last_seen": "2026-03-06T..."
}
```
`source` is either a filename from `input/` or `"api:REGION"`. `last_seen` is only present for API-sourced nodes.
