# macOS validation

Local validation on 2026-09-27: macOS 15.7.3, Apple Silicon, Python 3.11.4.
The application targets macOS 14 and later.

## Completed checks

- Backend: 405 tests passed.
- Frontend: 13 tests passed; Next.js production export completed.
- Native desktop: 6 Rust tests passed, including resource discovery and user-data paths.
- Packaged backend: native Paddle 3.2.2 matrix operations, PDF creation and SQLite
  FTS5 checks passed without the development Python environment.
- Packaged application smoke test passed using a temporary database: first launch
  before any account exists, registration, frontend serving and desktop status API.
- WKWebView opened the first-account registration screen in the actual On1y.app.
- The final ad-hoc signed application passed `codesign --verify --deep --strict`.
- Apple Silicon `.app` and `.dmg` artifacts were produced successfully.
- New Python integration/build scripts pass focused Ruff checks. The full repository
  Ruff run still reports existing style and static-analysis findings; it is not clean.

## Scope and remaining validation

The local package is for Apple Silicon. Intel builds and macOS 14 itself have not
been tested on hardware. There is no Developer ID signature or Apple notarization
in this preview build. Distribution is labelled as a macOS preview release.

Live platform synchronization requires the user's own accounts and cookies and
was not exercised. Paddle layout-model download and full inference were not part
of the packaged smoke test. PyInstaller reports upstream Paddle BLAS/LAPACK
library metadata and optional dependency warnings; the native smoke operations
pass, but hardened-runtime distribution needs separate validation.

## Reproduce

See [the macOS build guide](README.md#macos). After building:

```bash
.venv/bin/python scripts/smoke-macos.py desktop/src-tauri/target/release/bundle/macos/On1y.app
```

The first-install crash fixed during this work was caused by background sync
assuming that user 1 existed before registration. Background sync now selects
only existing active users, with regression tests for empty databases.

## Login configuration fix, 2026-09-27

A packaged installation could copy the commented `ON1Y_AUTH_SECRET_KEY` example
without generating an active key. Password verification succeeded, but token
creation raised an exception and the login endpoint returned HTTP 500. The
initial backend smoke test supplied a test key and therefore did not cover this
native initialization path.

Packaged startup now parses active assignments, generates a 256-bit OS-random key
for missing/empty/placeholder values, and repairs existing installations as well
as new ones. Valid existing keys and authentication settings are preserved.
Existing configuration is backed up to `.env.before-auth-fix`; replacement is
atomic, with private file permissions on macOS. Failures are no longer ignored.

Validation after the fix:

- All 12 native tests passed, including six authentication-configuration cases.
- All 16 focused backend account/macOS tests passed.
- Updated `.app` and `.dmg` bundles were generated and ad-hoc signature verified.
- The updated packaged smoke test passed registration and actual login using an
  isolated temporary account, plus the desktop and personal-sync API checks.
- Restarting the existing installation generated the missing key and backup;
  authentication stayed enabled and the existing account remained intact.

The updated bundle also includes the previously implemented personal-sync UI
and API. Sync remains opt-in; no relay deployment or user-data upload is performed
by the login repair.

## Windows archive import fix, 2026-09-27

The importer used `str.splitlines()` on `items.jsonl`. This also splits literal
Unicode separators inside JSON strings, including U+2028 in a Windows export,
and incorrectly reports an unterminated string. Records now split on LF only,
with CRLF still accepted. Invalid JSON reports the record line and column without
including document contents, and the archive closes on parsing failures.

Validation after the fix:

- All 449 backend tests passed, including 16 new archive regression cases.
- Tests cover U+0085/U+2028/U+2029, LF/CRLF, missing final newlines, HTTP import,
  lossless export/import, and rejection of truncated JSON before any writes.
- Read-only parsing of a large Windows archive returned every record declared
  in its manifest. The backup was not modified or imported into the live library.
- Updated `.app` and `.dmg` bundles were generated; the app's ad-hoc signature
  passed strict verification.
- The frozen-backend smoke test passed a synthetic Unicode archive import/export
  roundtrip in a temporary database, plus native dependencies, login, frontend,
  and personal-sync API checks.
- The existing app was restarted from the updated bundle. Authentication status
  returned HTTP 200 with authentication enabled and the existing user preserved.

## Archive conflict and responsiveness fixes, 2026-09-27

- Skipped records no longer update outgoing relations. They remain valid link
  targets for newly imported items. Duplicate URLs obey the same conflict policy.
- Overwrite imports remove absent summaries and themes and replace outgoing
  relations. Incoming links owned by other local items are preserved. Backup
  links can resolve to existing local targets outside the imported archive.
- The search index is refreshed after metadata restoration, so removed summaries,
  tags and themes do not remain searchable.
- The import HTTP handler runs in FastAPI's worker pool. Upload reading and
  SQLite connection creation, use and cleanup stay on the same worker.
- All 456 backend tests passed, including seven new regressions. A coordinated
  concurrency test verifies that another HTTP request completes while an import
  is paused in its worker, then allows the real import to finish.

Packaged smoke coverage now includes synthetic skip and overwrite imports in
addition to Unicode content preservation, using only a temporary database.
The rebuilt `.app` passed this smoke test and strict ad-hoc signature verification;
the updated `.dmg` was also generated successfully. The app was reopened with
the existing user data; authentication status returned HTTP 200 with the existing
account preserved. No real archive was imported as part of validation.

## macOS preview release preparation

- Final regression run: 459 backend tests, 17 frontend tests and 12 native Rust
  tests passed. Three added platform tests cover per-user Mac Literature paths,
  legacy Windows-default handling and the unchanged Windows default.
- Mac Literature data defaults to the user's writable data directory. Foreign
  Windows drive paths are rejected instead of being created inside the app.
- Release artifacts are Apple Silicon only, with ad-hoc signing and no Apple
  notarization. They are distributed as `v0.1.1-macos.1`; the application version
  remains 0.1.1. The Windows stable release is not replaced.
- Source and package checks exclude local databases, cookies, `.env` files and
  development toolchains. Only public configuration examples are staged.
