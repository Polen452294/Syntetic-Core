# Mobile Proxies, IP Rotation & Network Stealth

English · [Russian translation](ru/PROXIES.md)

Network-level anonymity is as crucial to bypassing anti-fraud systems as digital fingerprint spoofing. Naive automation tools often leak real IP addresses, use synthetic Python TLS fingerprints, or trigger race conditions on shared mobile modems.

Syntetic Core addresses network stealth through four architectural pillars:
1. **Native Browser TLS Stack:** Avoids synthetic HTTP/TLS signatures by routing the real browser's TCP traffic through a local SOCKS5 gateway.
2. **Hardware Modem Channel Locking:** Prevents multiple ports on the same physical cellular modem from interfering with each other.
3. **Automated Provider IP Rotation:** Interacts with mobile proxy provider HTTP APIs.
4. **Mandatory Exit IP Verification Probe:** Guarantees that the public exit IP has actually changed before opening a browser session.

---

## Supported Transports & Configuration

`ProxyConfig` supports `http://host:port`, `https://host:port`, and `socks5://host:port`:

```python
import os
from pydantic import SecretStr
from syntetic_core import CoreSettings, ProxyConfig, SynteticCore

mobile_proxy = ProxyConfig(
    id="mobile-modem-1",
    server="http://proxy.provider.example:28080",
    username=SecretStr(os.environ["PROXY_USERNAME"]),
    password=SecretStr(os.environ["PROXY_PASSWORD"]),
    kind="mobile",  # "mobile", "residential", or "datacenter"
)

core = SynteticCore(
    settings=CoreSettings(
        proxies=[mobile_proxy],
        proxy_required=True,  # Disallows unproxied connections to prevent real IP leaks
        allowed_target_hosts=["example.com", "api.ipify.org"],
    ),
    proxy_channels={"mobile-modem-1": "physical-usb-dongle-01"},
)
```

> [!IMPORTANT]
> If `proxy_required=True` is enabled, any failure to reach or authenticate with the proxy will immediately raise an error. Under no circumstances will Syntetic Core fall back to a direct, unproxied network connection.

---

## Hardware Modem Channel Locking (`proxy_channels`)

Many mobile proxy providers offer multiple ports that terminate on a single physical cellular USB modem or SIM card. Rotating the IP on one port inevitably changes the IP of the physical modem, disrupting all other active connections sharing that hardware.

Syntetic Core solves this with cross-process OS locks:
- Map multiple proxy IDs to a common channel name: `proxy_channels={"port-1": "modem-A", "port-2": "modem-A"}`.
- While a browser session is active on `port-1`, `modem-A` is locked.
- Any rotation attempt on `port-2` will fail immediately with `ProxyChannelLockedError`, preventing connection disruption.

---

## Automated HTTP Rotation & Exit IP Verification

Do not assume an API response of `{"success": true}` means the cellular modem has finished reconnecting to the cell tower.

The `rotate_ip` method coordinates provider API calls and independent verification:

```python
from syntetic_core import HttpRotationProvider

# Configure HTTP rotation call to your provider's API
provider = HttpRotationProvider(
    url=SecretStr(os.environ["ROTATION_API_URL"]),
    method="POST",  # POST / GET / PUT
    headers={"Authorization": SecretStr(os.environ["ROTATION_AUTHORIZATION"])},
    json_body={"modem_id": "dongle-01"},
    success_field="data.status",  # Optional: check specific JSON response field
    success_value="reconnecting",
    timeout_seconds=15,
)

# Rotate and verify exit IP before launching the next session
result = await core.rotate_ip(
    proxy_id="mobile-modem-1",
    provider=provider,
    probe_url="https://api.ipify.org?format=json",
    timeout_seconds=60,
    poll_seconds=2,
)

print(f"IP successfully rotated from {result.old_ip} to {result.new_ip}")
```

### Verification Pipeline:
1. Acquires exclusive OS lock for the proxy's hardware channel.
2. Probes the current public IP via `probe_url` through the proxy tunnel.
3. Calls the provider's HTTP rotation endpoint.
4. Repeatedly probes `probe_url` through the proxy until a **different public IP** is observed.
5. Releases the lock and records the new IP in `runtime-state.json`.

---

## Native Browser TLS vs. Library TLS

When tools like Python's `requests`, `httpx`, or `curl` make requests, their TLS ClientHello packets (ciphers, extensions, curves) form a distinctive JA3/JA4 fingerprint that anti-bot services (Cloudflare, Akamai, DataDome) immediately identify as non-browser traffic.

Syntetic Core uses a local SOCKS5 loopback `TargetProxy`:
- The browser process (Chromium / Firefox / WebKit) negotiates TLS directly over the TCP stream.
- The destination server sees genuine browser TLS handshakes matching the User-Agent and device recipe.
- No synthetic TLS hooks or MITM proxies are used, ensuring 100% TLS fingerprint consistency.
