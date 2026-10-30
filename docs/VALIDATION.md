# Validation · 3.5.3

Validated on 2026-10-28. Automated suite: **52 tests**, Python 3.14 locally;
GitHub CI also exercises Python 3.11. CI status is attached to the release.

## Automated coverage

PNG framing/CRC/hash/limits, retry deduplication, queue budgets, atomic projection
and backup, symlink rejection, pairing validation, first-image gallery lifecycle,
safe imv pruning, Numpad bindings, role installation plans, native Waybar clock,
battery integration, retired-input removal, startup rollback, stop without GUI
or network, service readiness, per-transfer UUID/hash confirmation and negative
ACK isolation. New tests cover stopped-client errors, immediate host-key failure,
sender lock timeout, missed local events, retry after fixing a destination,
gallery recovery beyond three failures, preservation of local project edits after
an incoming event, preserved stop state on user-only update,
and unlimited supervisor recovery with a fixed restart delay.

## Hardware validation

Both installed devices were upgraded through the documented `bash setup.sh
--update`, retaining their existing keys and scoped system transport. No root
configuration was changed. Configuration reload reported no Hyprland errors.

- A destination replaced by a directory returns a negative ACK; a following file
  succeeds without restarting the worker.
- Killing the file worker during a transfer results in automatic recovery and a
  confirmed file in projects.
- Killing the image queue results in a new ready worker; the RAM-loss boundary
  remains documented.
- Temporarily stopping the screenshot endpoint and restoring it during retries
  results in one confirmed image delivery.

- Suspending inotify while writing a test file is repaired by the 15-second
  reconciliation path without receiving a watcher event.
- A delivered test file was edited locally; its edits survived an actual
  reconciliation interval without a stale rewrite.
- Four consecutive SIGKILLs of the file worker recover without burst lockout.
- Sending while the client is stopped returns an actionable failure in 4.8 seconds
  in this deployment and does not restart the client.
- New numeric Waybar values are accepted, then a full restart clears them through
  this client's separate local customization.

Further details are recorded in the GitHub release notes.
These checks use the existing OS installations. They do not establish a fresh OS
installation, successful reboot, or delivery through every possible network outage.
Screenshots remain RAM-only on the client; stop/crash/power loss can lose pending
frames. A file confirmation timeout leaves the source intact and can coexist with
an already delivered copy.

## Release integrity

Two source archives built from unchanged files must be byte-identical. The CI
extracts the archive and checks every SHA-256 manifest entry. The archive contains
only an explicit source/documentation/test allowlist. Pairing profiles, private
keys, deployment configuration, screenshots and incoming documents are excluded.


# Page export · 3.6.0rc1

The full Python suite now contains **68 tests**. Added coverage includes document
schema/geometry bounds, complete visual tile coverage, PNG validation, ordered
choices and current field values, HTML escaping/CSP, source-script exclusion,
per-snapshot ACK/deduplication/collision checks, ten-document retention, native
message framing and stop during an in-flight page transfer. Page-viewer tests
cover duplicate-open prevention, a failed opener and malformed metadata without
crashing the screenshot supervisor.

Browser tests cover a rendered fixture with deliberately reordered choices,
current values different from HTML attributes, offscreen content, hidden/password
exclusions, retry with the same ID, capture-time mutation rejection and explicit
confirmation of incomplete exports. They use Chromium for DOM/orchestration and
an isolated real Firefox extension for the actual `tabs.captureTab` API.

On the installed Firefox 158, a 5379-CSS-pixel-tall fixture was captured in two PNG
tiles without scrolling. A second integration run used Firefox native messaging
and the existing pinned SSH endpoint to store JSON/HTML on the paired PC, verified
the matching ACK, and triggered its user-session page opener. Both devices run the
candidate through `setup.sh --update`; existing screenshot/SFTP diagnostics pass.

The user's actual Google Forms and its particular question types have not yet
been validated. The extension is unsigned and needs temporary loading for this
preview; a permanent Firefox installation requires the owner's Mozilla signing
workflow. No signing setting in the user's existing profile was changed.


# Nordic Reader · 3.6.0rc2

The Python suite remains at 68 tests. `tests/nordic.cjs` additionally verifies
respondent-domain restrictions, section deduplication, same-ID retry, warning
review and disconnect/queue clearing on disable. Its real Chromium DOM fixture
verifies Nordic styling, observation of changed sections, no resend for answer
selection, and theme/observer removal. The isolated Firefox 158 test additionally
enables/disables the actual bundled theme inside the extension content world.
Manual capture and all existing page-export browser tests continue to pass.

These fixtures are not a test against every Google Forms question type. No
user's real form was exported by the test. Temporary extensions still require
manual reload; this update does not change Mozilla signing protections.


# Legacy Forms and indicator fix · 3.6.0rc3

The suite has 70 Python tests, including a regression where Tailscale reports
Self.Online=false while BackendState is Running and the peer is reachable.
The browser queue and DOM tests now cover legacy /forms/viewform?id=... URLs,
canonical form identity without unrelated query parameters, legacy question
markup, and replacement of an older injected controller. Foreign origins,
editor URLs and missing/invalid legacy IDs remain excluded.

The real isolated-profile Firefox integration now additionally drives the full
content observer -> runtime message -> background capture -> automatic queue
pipeline on a legacy-path fixture. Only its temporary test clone admits the
loopback origin; production origin restrictions remain intact. CI mocks only the
native ACK in this variant. A local integration run used the real native port and
pinned SSH endpoint instead and obtained a matching durable ACK from the paired PC.

The supplied public form HTML was fetched separately for a read-only extraction
check: 8 questions and 27 options were recognized. Assets were blocked in that
static reproduction, so it is not evidence of complete live rendering. No form
submission was performed. User-profile activation still needs Firefox's temporary
extension reload and should be checked against the live form after that reload.


Follow-up reliability checks: reloading the same legacy section twice now produces
two fresh snapshot IDs, both with native ACKs in the real local Firefox test.
Same-visit retries still deduplicate; A -> B -> A is exercised in the rendered
content-controller test. Scrolling no longer invalidates capture solely because
scrollX/scrollY changed. Pending images receive a bounded loading grace period.
The supplied live form was also received on the paired PC after user reload:
8 questions, 27 options, one complete PNG tile, no warnings/unloaded images;
the HTML was nonempty and its page-opener request was recorded.


# Stable 3.6.1 · 2026-10-29

80 Python regression tests pass locally on Python 3.14. They include restart
without overwriting local project edits, replay of completed delivery metadata,
journal failure without a success receipt, explicit stop-marker preservation,
peer-key changes rejected in skip-root mode, bounded/strict JSON, receiver memory
limits and scoped removal of owned service drop-ins. Existing outage, ACK,
retention, gallery recovery, pairing and repeatable bootstrap tests remain in place.

Real Chromium DOM/capture orchestration and Nordic lifecycle tests pass. Firefox
Developer Edition 160 passes both isolated-profile capture and automatic legacy
section tests. The fixtures contain no user form data. Python compile checks,
shell syntax and reproducible source archive checks pass.

These are regression results, not a guarantee against every failure or an audit
certification. Clean installation and live pair verification are deployment steps
performed separately after the release commit is pushed.


# Clean-install correction · 3.6.2

The first real clean reinstall of 3.6.1 exposed a polkit rule load failure that
was absent when overwriting existing readable files. Root file publication now
sets permissions and ownership on a temporary file before atomic rename, including
when the invoking shell uses umask 077. The regression suite contains 81 tests.
Live clean deployment is checked separately after the corrected release is pushed.


# Hyprland installer compatibility · 3.6.3

92 Python tests cover existing transport behavior plus Lua/conf selection,
idempotent server source wiring, role and format changes, custom symlinks,
remembered config paths, uninstall cleanup and stopped-state preservation during
conf-based updates. An ambiguous fresh selection is rejected before the wizard
changes services. Config fixtures are tested without altering the running desktop;
this does not constitute a live session test on the user's new server.


# Independent theme and automatic queue · 3.6.4

Browser regressions cover automatic capture while the theme is initially off,
warning-bearing snapshots delivered without a head-of-line review gate, backlog
saturation preserving the native failure reason, same-ID retry and queue retention
through repeated theme toggles. Real Chromium content lifecycle tests verify that
disabling the theme continues section export and explicit controller stop ends it.
An isolated real Firefox auto-export test with the theme off received matching
native SSH ACKs from the paired PC. The 92 Python tests remain passing.
