# UX · 3.5.1

The installation flow is `git clone --branch v3.5.1`, then `bash setup.sh` on both
machines and exchange of public pairing profiles. No keyboard selection, evdev ACL
or input daemon is involved. The client has exactly three Numpad actions: start,
screenshot, stop. Waybar uses its native clock and an optional transport-tinted
battery module. Old answer display and input features are removed during upgrade.

For a clean installation, `waybridge uninstall` retains documents and archives
received data, while removing dedicated keys and configuration. Repeat the same
setup flow; fresh profiles are required. Real deployment verification belongs in
the release notes, separately from automated tests.
