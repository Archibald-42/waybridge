# Security

Waybridge is an explicitly configured transport and input tool. It is not a
security boundary against another process running under the same Linux UID.

Do not attach private SSH keys, Tailscale credentials, captured screens, incoming
code, configuration files, pairing profiles, or unredacted journals to public issues. Runtime data
lives outside the repository. The screenshot SSH endpoint accepts only a forced
command; the file endpoint accepts only chrooted SFTP. Pin host keys through an
authenticated channel; never bypass a changed host key warning.

Input starts OFF and is never automatically rearmed after a service restart.
Focus is checked at the compositor window level, not at the browser DOM level.
Kill switch stops the bridge's units and virtual input daemon. It does not stop
Tailscale or unrelated programs. SIGKILL and power loss erase RAM-only queues.

No process-name spoofing, code obfuscation, polymorphic builds, anti-debugging,
or claims of screen-capture exclusion are included. Source and releases remain
inspectable. Release checksums verify local integrity, not author identity.

If no private reporting channel is configured for a published fork, report only
a minimal sanitized reproducer in its issue tracker; send no secrets.

Pairing profiles contain public keys and deployment metadata only. Transfer them
through authenticated Taildrop or a trusted physical channel and compare the
profile code. Role/peer changes must also update root firewall/authorized keys;
the wizard refuses to skip that step for an existing different role or peer.
