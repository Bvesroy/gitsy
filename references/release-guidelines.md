# Release Engineering & Semantic Versioning Guidelines

1. **Follow Existing Versioning**: Inspect `git tag --list`, `package.json`, `pyproject.toml`, or `Cargo.toml` before proposing a version tag.
2. **Semantic Versioning (`vMAJOR.MINOR.PATCH`)**:
   - Increment `MAJOR` for incompatible API or CLI changes.
   - Increment `MINOR` for backward-compatible features.
   - Increment `PATCH` for backward-compatible bug fixes and documentation updates.
3. **Source Archives vs. Prebuilt Binaries**:
   - Explicitly label source distributions (`*-src.tar.gz`, `*-src.zip`) so users do not mistake them for compiled installers (`.dmg`, `.msi`, `.AppImage`).
   - Only package compiled binaries when built and verified on the target OS architecture.
4. **Checksum Integrity**:
   - Always generate `SHA256SUMS.txt` alongside downloadable release artifacts and include verification instructions (`shasum -a 256 -c SHA256SUMS.txt`).
5. **Non-Destructive Releases**:
   - Never delete or overwrite an existing published GitHub release or tag without explicit user permission.
