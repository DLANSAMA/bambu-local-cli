## 2025-02-27 - Predictable Temporary File Path in Health Checks
**Vulnerability:** Found `os.path.join(tempfile.gettempdir(), "printer_capabilities.json")` used as the default path for `doctor` capabilities output in `bambu_cli/commands/doctor.py`.
**Learning:** Hardcoding a predictable file name in a world-writable directory (`/tmp`) creates a local symlink attack vector. If an attacker pre-creates a symlink at that location pointing to a critical system file (e.g., `~/.bashrc`), running the `doctor` command would overwrite the target file with the user's privileges.
**Prevention:** Use `tempfile.mkstemp()` or `tempfile.NamedTemporaryFile()` to ensure that the OS safely generates a unique, unpredictable filename and exclusively creates it with restricted permissions.
