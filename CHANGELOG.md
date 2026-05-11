# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.1] - 2026-05-11

### Added

- **harness**: Backfill citation commit hashes and expand pricing table
- **janskie**: Wire corpus from user config; recover from tool input errors
- Sensible initial implementation but has hip-cargo deviations. Checkpoint before refactor

### Fixed

- Replace <CLI_COMMAND> with hip-cargo in tbump.toml
- Remove _container_image.py from [[file]] list in tbump
- Replace africalim with hip-cargo in can generation workflow
- **janskie**: Accept Model instances in build_agent for hermetic tests

### Miscellaneous

- Remove onboard command (M6.4)
- Initial install
- Initial project scaffold

### Testing

- Add roundtrip tests. build: add ripgrep and git to dockerfile


[0.0.1]: https://github.com/landmanbester/africalim/releases/tag/v0.0.1

