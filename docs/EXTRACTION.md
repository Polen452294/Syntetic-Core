# Extraction provenance and scope

English · [Russian translation](ru/EXTRACTION.md)

Extracted on **November 8, 2026**, from the local Synthetic Sessions working tree,
including uncommitted source changes present at that time. `extraction-manifest.json`
records original file SHA-256 hashes and path mappings. It identifies a source
snapshot, not the deployment state of any server.

## Included

57 Python browser-runtime modules and six resources: device emulation JavaScript,
the shared function-representation layer, a WebKit media sample, Chromium MV3
manifest/rules, and the Linux WebKit C filter. The pinned Camoufox installer/release
metadata and selected regression tests were also copied. Profile storage, credentials,
`.env`, cookies, browser executables, accumulated logs, and third-party diagnostic
JavaScript bundles were not copied.

## Adaptations

- Replaced `backend.app.*` / `worker.*` imports with standalone `syntetic_core._engine.*`.
- Extracted runtime settings with a dedicated environment prefix and no ambient `.env`.
- Retained ProxyConfig/ProxyManager; removed DB health/accounting and ORM imports.
- Retained local ProfileLock OS locking; removed Redis coordination.
- Retained target authorization; removed its full ScenarioDefinition dependency.
- Replaced the full scenario engine's EventSink dependency with a small typing Protocol.
- Capability discovery no longer advertises absent FingerprintJS/trace adapters.
- Removed ASGI middleware, DB instrumentation, and exporter server code from tracing/SRE;
  retained trace context and transport metrics.
- The public wrapper uses persistent profiles by default. `fresh=True` exposes the
  source new/cold mode. Archive cache cleanup and the S3 pipeline were not extracted.
- Preserved browser/session APIs, coherent recipes, seeds, and identity validation.
- Adapted regression tests to the new namespace/environment prefix. Excluded tests
  of the old controller CLI because that platform is not included.

## Added

Public `SynteticCore` and `BrowserSession`, a CLI, the generic RotationProvider
protocol, HTTP rotation adapter, independent exit verification, local channel
serialization, lifecycle/rotation tests, examples, and standalone documentation.

## Remaining in the source product

Dashboard/FastAPI, SQLAlchemy/Alembic, Redis/Dramatiq, Run/Session/Attempt authority,
leases/CAS, supervisor/cgroups, distributed archives and P2P Mesh, incubation, quotas,
external analytics balancing, and access-challenge recognition services. Some behavior
and scenario models remain as browser-helper dependencies; their presence does not
mean the original business workflow is available.

## Reproducing the extraction

`python tools/extract_engine.py /path/to/source` reproduces the mechanical extraction
baseline. Use a separate clean comparison copy: it overwrites internal modules.
It does not replace subsequent formatting, boundary review, tests, browser setup,
or maintenance of the new public API. Do not run it as a routine update over local
changes. Use the provenance manifest when comparing snapshots.

The user-supplied `inventory_updated.md` describes a historical October 27 snapshot.
Its embedded requirements and commands were reference data. This extraction used
the November 8 source code and accounted for later reports and known limitations.
