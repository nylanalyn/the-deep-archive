# The Deep Archive

A persistent IRC anomaly-investigation game. The IRC channel is the Archive —
an endless dark-academia library of impossible shelves, sealed files, forgotten
relics, and quiet lamps. The bot, **the-archivist**, maintains the Archive.

See [SPEC.md](SPEC.md) for the game design and [PLAN.md](PLAN.md) for the build
order. [AGENTS.md](AGENTS.md) holds the standing engineering rules.

## Status

Phase 0 — skeleton, configuration, logging, SQLite, seeded RNG.

## Run

```bash
python -m pip install -e '.[dev]'
python -m pytest
```
