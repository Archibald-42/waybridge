# Security

Waybridge transports screenshots, files and optional page snapshots over authenticated Tailscale/SSH.
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


After the user grants optional Firefox capture access, active Google Forms sections
are exported automatically, independently of the theme toggle. Disabling the add-on
or revoking its page access stops collection; stopping native transport alone
leaves the bounded browser RAM queue available for retry.
Firefox grants optional capture access;
a native messaging manifest authorizes only the fixed add-on ID. No HTTP listener,
cookie API or extra inbound port is used in production. Page packets have bounded
size, validated PNG tiles and complete geometry. The reader uses escaped text,
embedded PNG and a restrictive CSP instead of executing source markup/scripts.
The paired SSH key is authorized to publish both images and page snapshots.

Only the current available document is exported, including its visible content
and current entered values. Private tabs are rejected. Query/fragment, cookies,
localStorage and HTTP headers are not collected. Pending snapshots remain in
extension RAM for retry; stopping the transport does not clear that browser RAM.
Snapshots on the receiving PC are retained locally (last ten) and preserved on
uninstall. Removing the native application does not uninstall a separately installed
Firefox add-on; remove it through Firefox's Add-ons Manager when appropriate.

Dedicated SSH receive/native-host child processes lower their address-space limit
to at most 768 MiB; stricter existing limits are retained. JSON protocol documents
reject duplicate keys, non-finite constants and nesting beyond 64 levels. These
limits bound individual child processes, not aggregate connections or disk usage.
The paired peer remains trusted to upload files and snapshots within those limits.
