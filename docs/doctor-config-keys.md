# Doctor check: ignored config keys

`binnacle doctor` (check group `config-keys`) reads the active config file
(`BINNACLE_CONFIG_FILE`, else `~/.config/binnacle/config.toml`) and WARNs once per key path that `Settings()` silently ignores, with a `did you mean` hint
(difflib, cutoff 0.8, the same as the `[roots]` near-miss). It prints key paths only, never values. It is OK when every key is known, and FAILs only when the file cannot be parsed.

- Reported: an unknown key inside a known section (`search_text.timout_s`), an unknown top-level table, and removed keys that are still present.
- Not reported: unknown `[roots]` keys and roots-like top-level keys, which already fail start-up; nested tables of dict-valued settings (`client_tools`, `run_command.auto_background_patterns`).
- Top-level tables owned by another tool are allowlisted in `FOREIGN_TABLES` (`src/binnacle/config_unknown_keys.py`): `watchdog` (binnacle-watchdog). Add an entry only with its owner.
