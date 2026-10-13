# ripgrep pin

Binnacle pins ONE ripgrep version for the Pi, the Mac, and CI: **15.2.0**.

- CI installs 15.2.0 from the upstream release archive and verifies its
  SHA-256 before use (`.github/workflows/ci.yml`, step "Install ripgrep").
- `binnacle doctor` reports the ripgrep in use (check group `ripgrep`). It
  WARNs when the version differs from `PINNED_RG_VERSION` in
  `src/binnacle/diagnostics/doctor_provenance.py`.
- Hosts point `rg_bin` (top-level key in `config.toml`) at a user-level
  binary. Do not rely on the system or Homebrew `rg`.

## Change the pin

1. Pick the new version and read its upstream `.sha256` files.
2. Update `PINNED_RG_VERSION`, `RG_VERSION`, and `RG_SHA256` in `ci.yml`.
3. Install the new binary on each host and update `rg_bin`.

## Archives and SHA-256 (15.2.0)

|Target|SHA-256|
|---|---|
|`aarch64-unknown-linux-gnu` (Pi)|`a740b91c82eaf9914cfedd353572f2791cbe0162c84101ee0951058f4dcbc90d`|
|`x86_64-unknown-linux-musl` (CI)|`33e15bcf1624b25cdd2a55813a47a2f95dbe126268203e76aa6a585d1e7b149c`|

Context: PF-T3-02 was first read as an rg-major difference. It is not. The pin
stays as hygiene so that an output-format change between majors cannot
become a parity break.
