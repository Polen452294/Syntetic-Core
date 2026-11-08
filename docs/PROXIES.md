# Proxies and provider API IP rotation

English · [Russian translation](ru/PROXIES.md)

## Three separate operations

1. **Assign a proxy:** the profile retains `proxy_id`; credentials are supplied in Settings.
2. **Rotate the exit address:** the provider API changes the physical/logical channel's IP.
3. **Verify:** the core observes a different public IP through that proxy.

A different port need not imply a different IP. API `success=true` does not prove
that the channel has already switched. Changing an IP does not create a new
hardware identity.

## Supported transport

`ProxyConfig(server=...)` accepts `http://host:port`, `https://host:port`, and
`socks5://host:port`. Supply credentials separately as SecretStr. Proxy URL userinfo
is rejected. Authenticated SOCKS5 is rejected by the retained runtime contract;
use authenticated HTTP CONNECT or SOCKS5 without authentication.

```python
proxy = ProxyConfig(
    id="mobile-1", server="http://proxy.provider.example:28080",
    username=SecretStr(os.environ["PROXY_USERNAME"]),
    password=SecretStr(os.environ["PROXY_PASSWORD"]), kind="mobile",
)
```

Provider name, country/region/asn are metadata, not proof of exit geography.
`ProxyConfig.metadata()` excludes username/password/change_ip_url.

## Generic HTTP adapter

```python
provider = HttpRotationProvider(
    url=SecretStr(os.environ["ROTATION_API_URL"]),
    method="POST",
    headers={"Authorization": SecretStr(os.environ["ROTATION_AUTHORIZATION"])},
    json_body={"port": 28080},
    success_field="data.success",
    success_value=True,
    timeout_seconds=15,
)
result = await core.rotate_ip(
    "mobile-1", provider,
    probe_url="https://api.ipify.org?format=json",
    timeout_seconds=60,
    poll_seconds=2,
)
```

Choose the URL, method, headers, body, and success field from your provider's actual
API and plan documentation. This is a configurable adapter, not a verified integration
with a specific supplier. URL/header secrets are hidden from repr. The body is also
excluded from repr; do not log or publish the entire configuration.

With `success_field=None`, HTTP 2xx is required. A configured field additionally
checks the JSON value and its type. JSON responses are limited to 64 KiB. Redirects
are prohibited, HTTPS is required, and ambient HTTP_PROXY/HTTPS_PROXY settings are
ignored. Rotation requests are not automatically retried: a retry could trigger a
second IP change.

## Exit verification

The core probes the old IP before requesting rotation, then polls until a different
public IP appears. The probe URL must return a plain IP or a supported JSON IP
object and must be in `allowed_target_hosts`. Probes use TargetProxy and the assigned
upstream. Temporary modem disconnection is tolerated within the overall deadline.
Timeout, invalid output, or an unchanged IP produces `ProxyUnavailableError` without
a direct-connection fallback.

You may use your own HTTPS probe instead of a public IP service. It must report
the actual source address of the connection.

## Custom providers

```python
class MyProvider:
    async def rotate(self, proxy: ProxyConfig) -> None:
        # Call the supplier's SDK/API and wait for the request to be accepted.
        # Raise on rejection. Do not open a browser session here.
        await my_sdk.rotate_port(proxy.id)

result = await core.rotate_ip("mobile-1", MyProvider(), probe_url=probe_url)
```

This satisfies `RotationProvider`. Implementations may call an SDK, sign requests,
or wait for a provider job. The core owns the overall deadline, channel lock, and
independent IP verification. asyncio cancellation propagates to the caller.

## Shared modems and concurrency

```python
core = SynteticCore(
    "data/profiles", settings=settings,
    proxy_channels={"port-1": "modem-A", "port-2": "modem-A"},
)
```

Without a mapping, the lock key is derived from the endpoint. Different ports on
one physical modem must share a channel ID. All cooperating processes must use the
same profile_root and channel map. Multiple hosts need an external coordinator.
Manual provider API requests and other applications bypass this local protection.

The lock is held until the browser session is fully closed. Rotate only between
sessions. A busy channel raises `ProfileLockedError` without contacting the provider.
Do not call `rotate_ip` inside `async with core.session(...)` for the same channel.

The retained identity policy may reject rapid exit changes for persistent nonmobile
profiles. Use `kind="mobile"` for managed mobile rotation. Rotation does not change
a profile's timezone, locale, or geolocation: select a matching provider region or
create a new coherent identity.

## Connecting a real supplier

1. Obtain the proxy endpoint, credentials, rotation API, and shared-channel topology.
2. Configure the adapter from the supplier's documented API contract.
3. Keep secrets in environment variables or your application's secret store.
4. Authorize exact target/resource/probe hosts.
5. Confirm rotation in a separate call, then open the profile.
6. Verify geography and IP stability for your workload.

No provider keys or paid API calls were used during extraction. The core does not
automatically top up balances, purchase/rent IPs, change plans, or cycle accounts.
