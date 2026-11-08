# Troubleshooting

English · [Russian translation](ru/TROUBLESHOOTING.md)

## RuntimeCompatibilityError

Run `syntetic-core doctor` in the same virtual environment, display mode, and OS
account. Inspect `installed`, `smoke_test`, `limitations`, and `parameters`. Do not
manually promote a runtime in the manifest: the generator and factory must agree
with actual capabilities. iOS is unsupported on Windows.

## BrowserLaunchError / driver guard

Run `syntetic-core prepare --engine chromium` before starting jobs. Verify Playwright
1.62.0, installed browser binaries, and required system libraries. The patch must
be present in the current Python environment's driver. For Camoufox, separately run
`tools/setup_browser.py` and check the pinned build's installation path.

## ProfileValidationError

A saved identity, hash, engine, version, or observed geometry does not match. Preserve
the data for inspection. Create a new ID for a different configuration instead of
removing individual identity files or recalculating a used profile's hash. Mobile
pages need appropriate `<meta name="viewport">` markup. Checks account for native
viewport scale but do not permit arbitrary device changes.

## ProfileLockedError

The profile or proxy/modem channel is already in use. Wait for its owner to finish
or choose a separate profile/channel. A `.lock` file can remain after closure:
OS lock state determines ownership, not file existence. Do not delete active lock files.

## Incomplete pages or blocked requests

Check exact resource hosts, redirects, and `www` variants. Local fixtures also need
`trusted_local_target_hosts`. Temporarily disable explicit resource optimization
for comparison: CSS/font filtering changes rendering and may break a site. Enable
filters based on measurements for the actual task.

## The IP did not change

Check the API method, credentials, plan behavior, and physical channel mapping.
Increasing the timeout does not fix an API rejection. HTTP 2xx may mean only that
a job was accepted; the core waits for a changed IP through the actual upstream.
Do not blindly repeat rotation after an uncertain result.

## Cookies/localStorage are not retained

Use the same ID and profile_root, and finish the async context manager normally.
Origins/subdomains have different storage scopes. `fresh=True` is for a single-use
profile, not persistent authentication. Do not delete browser-data between sessions.
The site itself may clear or restrict storage.

## Excessive RAM use

Limit concurrency and measure typical page resource use. Each persistent context
starts a separate browser. This package excludes the source cluster's resource
supervisor and cgroups. It does not hide resource exhaustion by automatically
retrying with additional browser processes.
