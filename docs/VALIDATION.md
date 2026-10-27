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
