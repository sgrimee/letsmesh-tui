# meshcore-nodes

A CLI tool to maintain a database of MeshCore node public keys and look up node names by key prefix.

## Usage

```
lma nodes update [--region REGION]   update database from input files and APIs
lma nodes lookup <hex_prefix>        find node(s) by key prefix (1+ hex chars)
lma nodes list [--by-key]            list all nodes (default: sort by name)
lma monitor [--region REGION] [--poll SECONDS]   live packet monitoring TUI
```

### Examples

```sh
# Rebuild the database
lma nodes update

# Look up by first byte of public key
lma nodes lookup 7d

# Look up by two bytes
lma nodes lookup ab4b

# List all nodes sorted alphabetically
lma nodes list

# List all nodes sorted by public key
lma nodes list --by-key

# Start live packet monitor
lma monitor
```

## Data sources

### Input files (`input/*.txt`)

Static node lists maintained manually. Format (one node per line):

```
name   TYPE   pubkey_hex   [routing]
```

- `name` — node name
- `TYPE` — `CLI` (client) or `REP` (repeater)
- `pubkey_hex` — hex public key, full 64 chars or a shorter prefix
- `routing` — optional, e.g. `Flood` or `0 hop`

Lines may optionally be prefixed with a line number (`1→`).

### Live APIs

On `lma nodes update`, the tool fetches data from two sources:

- **letsmesh** (`api.letsmesh.net`) — node list for the region; partial keys from input files are matched and upgraded to full 64-char keys. Use `--region` to select a region (default: `LUX`).
- **map.meshcore.dev** — node coordinates (lat/lon); backfills any node in the database that lacks coordinates.

## Database

The database is stored in `nodes.json` (gitignored, auto-generated). Run `nodes update` to create or refresh it.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync --all-extras
uv run lma nodes update
```

Or install as a tool:

```sh
uv tool install --all-extras .
lma nodes update
```
