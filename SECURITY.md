# Security

Waybridge 3.5 transports screenshots and files over authenticated Tailscale/SSH.
It has no keyboard interception, synthetic input, answer overlay or clock replacement.
The Waybar battery indicator reports transport readiness; it does not acknowledge
individual screenshot deliveries.

Dedicated endpoints use a chrooted SFTP account or a forced receive command.
Host keys must be pinned through authenticated public profiles. Do not bypass
changed-key warnings. Bindings require no /dev/input or /dev/uinput access.

Stop terminates only Waybridge services. It does not stop Tailscale or unrelated
applications. RAM queues disappear on stop, SIGKILL and power loss. A process
running under the same Linux UID is outside the application's trust boundary.

Never attach private keys, pairing profiles, deployment configs, screenshots,
received documents or unredacted logs to public issues. Release checksums verify
local integrity, not author identity. Keep reports minimal and sanitized.

Uninstall preserves project documents and archives incoming files and screenshots
outside the removed runtime. It removes dedicated transport keys; fresh pairing
is required after a clean reinstall. General-purpose system packages are retained.
