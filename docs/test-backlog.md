# Test backlog

Prioritized testing gaps after the 2026-07 modular refactor (`bambu.py` split
into `download.py`, `job.py`, `setup_cmd.py`, `camera.py`, `constants.py`).
All 288 existing tests pass; coverage below is from `pytest --cov=bambu_cli`.

## Ground rules for new tests

- Run everything with `uv run --extra test python -m pytest` plus
  `python3 -W error::ResourceWarning -m unittest tests.test_bambu`.
- Never touch a real printer or the network. Use `--sim` for CLI-level tests
  (see `tests/agent_cli_smoke.py`) or mock at module seams.
- Patch targets: patch functions **in the module that calls them**, e.g.
  `bambu_cli.download.build_safe_opener`, `bambu_cli.download.resolve_printables_url`.
  Runtime state (`PRINTER_IP`, `SIMULATION_MODE`, `ORCA_SLICER`, `CONFIG_PATH`,
  `_cfg`) is patched on `bambu_cli.bambu` — all modules read it from there.
  `logger` is also patchable as `bambu_cli.bambu.logger` (LoggerProxy).
- JSON contracts are load-bearing for agents: assert full payload shapes
  (`status`, `command`, `failed_step`, `exit_code`, `next_command`), not just
  exit codes. `docs/api.md` and `bambu_cli/AGENTS.md` describe the contracts.
- Don't add new `isinstance(x, Mock)` or `"unittest" in sys.modules` branches
  to production code; if a test needs one, restructure the test instead.

## Priorities

### P1 — `job.py` (12% coverage)
The `job`/`send` orchestrator is the primary agent entry point and the least
covered module. Mock `bambu.cmd_download/cmd_slice/cmd_upload/cmd_print` and
cover:
- Delegated-step failure payloads: `download_error`/`slice_error`/
  `upload_error`/`print_error` detail objects now flow through
  `bambu_cli.utils._LAST_ERROR_PAYLOAD` (this was broken before the refactor —
  regression-test it explicitly).
- `next_command` payloads for `uploaded`, `uploaded_not_printed`, and the
  print-failure `["status", "--json"]` + `recovery_hint` path.
- Dry-run matrix: direct URL (.stl/.zip/.3mf), local model, local ZIP, local
  printer-ready file — assert `would_*` flags, `remote_name`, and
  `would_create_output_dir`.
- ZIP paths: bad zip, no supported member, oversized member, unsafe member
  filename, `archive_entry` propagation into the summary.
- `--output` handling: created when needed, ignored for printer-ready local
  files, invalid/`-`-prefixed values, temp workdir cleanup.

### P2 — `setup_cmd.py` (35%)
- Non-interactive setup: each missing-value/placeholder/conflicting-flag
  error payload; `--access-code-env`; existing vs new `--access-code-file`;
  directory and config-path-collision rejections.
- `collect_preflight_checks` / `_cmd_preflight`: ok/warning/error matrices,
  `--strict`, file-permission warnings (chmod a tmp file to 0644).
- `_parse_mdns_printer_identity` and `_service_info_address` edge cases.
- Guided setup: headless-stdin rejection, manual fallback when zeroconf is
  missing (patch the import), multi-printer selection bounds.

### P3 — `download.py` (49%)
Existing tests cover the happy paths and SSRF basics. Missing:
- Redirect handling: redirected URL revalidation, unsupported redirected
  extension, filename recomputation after redirect.
- HTML resolution loop: 3-attempt exhaustion, filename-hint attributes,
  candidate priority (STL beats 3MF beats ZIP), dedup.
- Content-Disposition: RFC 2231 `filename*`, archive-vs-model switching,
  interaction with `--name`.
- Size limits: Content-Length rejection vs mid-stream limit, short reads,
  empty files, partial-file cleanup on each error path.
- `_get_safe_connection`: DNS cache TTL expiry/eviction, IPv6-mapped IPv4
  blocking, all-IPs-unreachable cache invalidation (patch
  `bambu_cli.download.socket`).

### P4 — `camera.py` (68%)
- `_grab_camera_frame_direct`: fingerprint match/mismatch/missing-pin paths
  (fake TLS socket), frame-scan loop bounds, oversized-frame skip.
- Docker fallback: container-name/image/port taken from config
  (`camera_container_name` regression-tested — it broke once), access-code
  redaction in error output, localhost-only streamer URL enforcement.
  Patch `bambu_cli.camera.subprocess` / `bambu_cli.camera.shutil`.

### P5 — protocols (`mqtt.py` 54%, `ftps.py` 58%)
- MQTT: retry/timeout paths in `send_command`/`get_status`, cert-pin
  verification failures, `_SimMqttClient` behavior.
- FTPS: resume/retry in upload, `_noncolliding_path` collisions,
  ConnectionManager reuse/close-all.

## Known debt (do NOT "fix" silently while adding tests)

- Production code contains test-awareness (`isinstance(x, Mock)`,
  `"unittest" in sys.modules`, `BAMBU_TESTING`). Removing it is a separate,
  deliberate task; new tests should not depend on adding more of it.
- `bambu.py` is a compatibility facade with wildcard re-exports; new code
  should import from the concrete modules, and new re-exports are only added
  when something must be patchable via `bambu.<name>`.
