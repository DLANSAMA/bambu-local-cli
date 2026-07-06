import os
import sys
import json
import time
import tempfile

from bambu_cli.logging_utils import logger

# We dynamically import bambu at runtime in every function to support patching of functions and configuration globals

def cmd_setup(args):
    """Interactive or non-interactive printer configuration setup."""
    from bambu_cli import bambu
    bambu._cmd_setup(args)
from bambu_cli.utils import get_sequence_id

def cmd_doctor(args):
    """Health-check: auto-discover printer capabilities and verify configuration."""
    from bambu_cli import bambu
    from bambu_cli.cli import _namespace_get, _display_path
    from bambu_cli.utils import emit_json
    from bambu_cli.cli import _path_for_message, _exception_for_message
    from bambu_cli.cli import EXIT_FILE_ERROR, EXIT_CONFIG_ERROR, EXIT_NETWORK_ERROR
    from bambu_cli.protocols.mqtt import get_status, get_version, probe_cert_fingerprint
    from bambu_cli.protocols.ftps import get_ftp
    
    json_mode = bool(_namespace_get(args, "json", False))

    def emit_doctor_failure(failed_step, exit_code, error, extra=None):
        if not json_mode:
            return
        payload = {
            "command": "doctor",
            "ok": False,
            "status": "error",
            "failed_step": failed_step,
            "exit_code": exit_code,
            "error": error,
        }
        if extra:
            payload.update(extra)
        emit_json(payload)

    cap_path = _namespace_get(args, "output") or os.path.join(tempfile.gettempdir(), "printer_capabilities.json")
    cap_path = bambu._expand_path(cap_path)
    if cap_path.startswith('-'):
        message = f"Invalid output path: {_path_for_message(cap_path)}"
        logger.error(message)
        emit_doctor_failure("validate", EXIT_FILE_ERROR, message)
        sys.exit(EXIT_FILE_ERROR)
    try:
        bambu._ensure_parent_dir(cap_path)
    except SystemExit as exc:
        emit_doctor_failure(
            "validate",
            bambu._exit_code_from_system_exit(exc, EXIT_FILE_ERROR),
            f"Could not prepare output path: {_path_for_message(cap_path)}")
        raise

    logger.info("🩺 Running Bambu printer health check...")

    logger.info(f"   [1/3] Checking config at {_display_path(bambu.CONFIG_PATH)}...")
    try:
        cfg = bambu.load_config()
        logger.info("   ✅ Config loaded successfully.")
    except SystemExit:
        logger.error("   ❌ Config check failed.")
        emit_doctor_failure("config", EXIT_CONFIG_ERROR, "Config check failed.")
        sys.exit(EXIT_CONFIG_ERROR)

    try:
        fp = probe_cert_fingerprint(bambu.PRINTER_IP, 990, timeout=5)
    except Exception:
        fp = None

    def log_pin_hint():
        if fp and not bambu._expected_fingerprint() and not bambu.INSECURE_TLS:
            logger.info("      The printer uses a self-signed certificate. Pin it by adding to config.json:")
            logger.info(f'        "cert_fingerprint": "{fp}"')
            logger.info("      then re-run doctor.")

    logger.info(f"   [2/3] Verifying MQTT connectivity to {bambu.PRINTER_IP}:{bambu.MQTT_PORT}...")
    status = get_status(timeout=5)
    if status:
        logger.info("   ✅ MQTT connection established. Printer identified.")
    else:
        message = f"MQTT connection failed. Ensure printer at {bambu.PRINTER_IP} is on and access code is correct."
        logger.error(f"   ❌ {message}")
        log_pin_hint()
        extra = {"certificate_fingerprint": fp} if fp else None
        emit_doctor_failure("mqtt", EXIT_NETWORK_ERROR, message, extra=extra)
        sys.exit(EXIT_NETWORK_ERROR)

    logger.info(f"   [3/3] Verifying FTPS connectivity to {bambu.PRINTER_IP}:990...")
    try:
        with get_ftp(timeout=5) as ftp:
            logger.info("   ✅ FTPS connection established.")
    except Exception as e:
        message = f"FTPS connection failed: {e}"
        logger.error(f"   ❌ {message}")
        log_pin_hint()
        extra = {"certificate_fingerprint": fp} if fp else None
        emit_doctor_failure("ftps", EXIT_NETWORK_ERROR, message, extra=extra)
        sys.exit(EXIT_NETWORK_ERROR)

    if fp:
        logger.info(f"   🔐 Printer certificate SHA-256: {fp}")
        if bambu._expected_fingerprint() == fp:
            logger.info("      ✅ Matches the pinned cert_fingerprint in your config.")
        elif bambu._expected_fingerprint():
            logger.warning("      ⚠️  Does NOT match the cert_fingerprint in your config!")
        else:
            logger.info('      Add "cert_fingerprint": "<above>" to config.json to pin this connection.')

    model_info = bambu.MODEL_MAPPING.get(bambu.PRINTER_MODEL, bambu.MODEL_MAPPING["P1P"])
    firmware = status.get("sw_ver")
    modules = get_version(timeout=5)
    if modules:
        ota = next((m for m in modules if m.get("name") == "ota"), None) or modules[0]
        firmware = ota.get("sw_ver") or firmware

    capabilities = {
        "model": status.get("hw_ver") or model_info["full_name"],
        "firmware": firmware or "Unknown",
        "serial": bambu._redacted_serial(),
        "capabilities": {
            "ams": "ams" in status,
            "chamber_light": True,
            "camera_snapshot": bambu.PRINTER_MODEL in ("P1P", "P1S"),
            "camera_snapshot_note": "snapshot uses the optional BambuP1Streamer container and is intended for P1P/P1S"
        }
    }

    try:
        with open(cap_path, 'w', encoding="utf-8") as f:
            json.dump(capabilities, f, indent=2)
    except OSError as e:
        message = f"Could not write printer capabilities to {_path_for_message(cap_path)}: {_exception_for_message(e)}"
        logger.error(message)
        emit_doctor_failure("output", EXIT_FILE_ERROR, message, extra={"output": cap_path})
        sys.exit(EXIT_FILE_ERROR)
    logger.info(f"\n✨ Printer Details: Model={capabilities['model']}, Firmware={capabilities['firmware']}, Serial={capabilities['serial']}")
    logger.info(f"✅ All checks passed! Printer capabilities saved to {_display_path(cap_path)}")
    if json_mode:
        # Mask IP address inside doctor capabilities report unless --verbose is checked (A0530-SEC-16)
        reported_ip = bambu.PRINTER_IP if bool(_namespace_get(args, "verbose", False)) else "<redacted>"
        emit_json({
            "command": "doctor",
            "ok": True,
            "status": "ok",
            "output": cap_path,
            "printer_ip": reported_ip,
            "certificate_fingerprint": fp,
            "capabilities": capabilities,
        })

def cmd_light(args):
    """Control chamber light."""
    from bambu_cli.cli import _namespace_get
    from bambu_cli.utils import emit_json, emit_json_error, EXIT_NETWORK_ERROR
    from bambu_cli.protocols.mqtt import send_command
    action = args.action  # on or off
    val = "on" if action == "on" else "off"
    payload = json.dumps({
        "system": {"sequence_id": get_sequence_id(), "command": "ledctrl",
                   "led_node": "chamber_light", "led_mode": val,
                   "led_on_time": 500, "led_off_time": 500}
    })
    if not send_command(payload):
        message = "Failed to send light command."
        logger.error(message)
        emit_json_error(args, "light", EXIT_NETWORK_ERROR, message, failed_step="mqtt", action=action, changed=False)
        sys.exit(EXIT_NETWORK_ERROR)
    logger.info(f"💡 Light turned {action}")
    if bool(_namespace_get(args, "json", False)):
        emit_json({
            "status": "light_changed",
            "command": "light",
            "action": action,
            "changed": True,
        })

def cmd_pause(args):
    """Pause current print."""
    from bambu_cli.cli import _namespace_get
    from bambu_cli.utils import emit_json, emit_json_error, EXIT_NETWORK_ERROR
    from bambu_cli.protocols.mqtt import send_command
    payload = json.dumps({"print": {"sequence_id": get_sequence_id(), "command": "pause"}})
    if not send_command(payload):
        message = "Failed to send pause command."
        logger.error(message)
        emit_json_error(args, "pause", EXIT_NETWORK_ERROR, message, failed_step="mqtt", paused=False)
        sys.exit(EXIT_NETWORK_ERROR)
    logger.info("⏸️  Print paused")
    if bool(_namespace_get(args, "json", False)):
        emit_json({
            "status": "paused",
            "command": "pause",
            "paused": True,
        })

def cmd_resume(args):
    """Resume paused print."""
    from bambu_cli.cli import _namespace_get
    from bambu_cli.utils import emit_json, emit_json_error, EXIT_NETWORK_ERROR
    from bambu_cli.protocols.mqtt import send_command
    payload = json.dumps({"print": {"sequence_id": get_sequence_id(), "command": "resume"}})
    if not send_command(payload):
        message = "Failed to send resume command."
        logger.error(message)
        emit_json_error(args, "resume", EXIT_NETWORK_ERROR, message, failed_step="mqtt", resumed=False)
        sys.exit(EXIT_NETWORK_ERROR)
    logger.info("▶️  Print resumed")
    if bool(_namespace_get(args, "json", False)):
        emit_json({
            "status": "resumed",
            "command": "resume",
            "resumed": True,
        })

def cmd_stop(args):
    """Stop current print."""
    from bambu_cli.cli import _namespace_get
    from bambu_cli.utils import emit_json, emit_json_error, EXIT_COMMAND_ERROR, EXIT_NETWORK_ERROR
    from bambu_cli.protocols.mqtt import send_command
    if not args.confirm:
        logger.warning("⚠️  This will STOP the current print. Add --confirm to proceed.")
        if bool(_namespace_get(args, "json", False)):
            emit_json({
                "status": "confirmation_required",
                "command": "stop",
                "stopped": False,
                "next_command": ["stop", "--confirm", "--json"],
            })
        sys.exit(EXIT_COMMAND_ERROR)
    payload = json.dumps({"print": {"sequence_id": get_sequence_id(), "command": "stop"}})
    if not send_command(payload):
        message = "Failed to send stop command."
        logger.error(message)
        emit_json_error(args, "stop", EXIT_NETWORK_ERROR, message, failed_step="mqtt", stopped=False)
        sys.exit(EXIT_NETWORK_ERROR)
    logger.info("⏹️  Print stopped")
    if bool(_namespace_get(args, "json", False)):
        emit_json({
            "status": "stopped",
            "command": "stop",
            "stopped": True,
        })

def cmd_upload(args):
    """Upload a file to the printer via FTPS with binary retry/resume."""
    from bambu_cli import bambu
    from bambu_cli.cli import _namespace_get
    from bambu_cli.utils import emit_json, emit_json_error
    from bambu_cli.cli import EXIT_FILE_ERROR, EXIT_NETWORK_ERROR
    
    filepath = bambu._expand_path(args.file)
    if filepath.startswith('-'):
        message = f"Invalid filepath: {bambu._path_for_message(filepath)}"
        logger.error(message)
        emit_json_error(args, "upload", EXIT_FILE_ERROR, message, failed_step="validate", file=filepath)
        sys.exit(EXIT_FILE_ERROR)
    if not os.path.exists(filepath):
        message = f"File not found: {bambu._path_for_message(filepath)}"
        logger.error(message)
        emit_json_error(args, "upload", EXIT_FILE_ERROR, message, failed_step="validate", file=filepath)
        sys.exit(EXIT_FILE_ERROR)
    if bambu._is_directory_input(filepath):
        message = bambu._directory_input_message(filepath)
        logger.error(message)
        emit_json_error(args, "upload", EXIT_FILE_ERROR, message, failed_step="validate", file=filepath)
        sys.exit(EXIT_FILE_ERROR)

    filename = bambu._portable_basename(filepath)
    if bambu._safe_remote_name(filename) is None:
        message = f"Refusing to upload file with unsafe name: {bambu._name_for_message(filename)!r}"
        logger.error(message)
        emit_json_error(args, "upload", EXIT_FILE_ERROR, message, failed_step="validate", file=filepath, remote_name=filename)
        sys.exit(EXIT_FILE_ERROR)
    if not bambu._is_print_ready_name(filename):
        message = bambu._print_ready_error_message(filename, "upload")
        logger.error(message)
        emit_json_error(args, "upload", EXIT_FILE_ERROR, message, failed_step="validate", file=filepath, remote_name=filename)
        sys.exit(EXIT_FILE_ERROR)
    try:
        filesize = os.path.getsize(filepath)
    except OSError as exc:
        message = f"Could not read file size for {bambu._path_for_message(filepath)}: {bambu._exception_for_message(exc)}"
        logger.error(message)
        emit_json_error(args, "upload", EXIT_FILE_ERROR, message, failed_step="validate", file=filepath, remote_name=filename)
        sys.exit(EXIT_FILE_ERROR)
    if filesize <= 0:
        message = f"Refusing to upload empty file: {bambu._path_for_message(filepath)}"
        logger.error(message)
        emit_json_error(args, "upload", EXIT_FILE_ERROR, message, failed_step="validate", file=filepath, remote_name=filename, bytes=filesize)
        sys.exit(EXIT_FILE_ERROR)

    if getattr(args, 'dry_run', False):
        logger.info(f"🔍 Dry Run: Validating printer connectivity for {filename}...")
        try:
            with bambu.get_ftp(timeout=5) as ftp:
                logger.info("   ✅ Printer reachable.")
            logger.info(f"   ✅ Local file {bambu._path_for_message(filepath)} exists ({filesize // 1024}KB)")
            if bool(_namespace_get(args, "json", False)):
                emit_json({
                    "status": "dry_run_ok",
                    "command": "upload",
                    "file": filepath,
                    "remote_name": filename,
                    "bytes": filesize,
                    "uploaded": False,
                })
            return filename
        except Exception as e:
            message = f"Dry run failed: {e}"
            logger.error(message)
            emit_json_error(args, "upload", EXIT_NETWORK_ERROR, message, failed_step="dry_run", file=filepath, remote_name=filename)
            sys.exit(EXIT_NETWORK_ERROR)

    logger.info(f"📤 Uploading {filename} ({filesize // 1024}KB)...")

    max_retries = 3
    retry_delay = 5
    uploaded_bytes = 0

    for attempt in range(max_retries + 1):
        try:
            with bambu.get_ftp(timeout=bambu.UPLOAD_TIMEOUT) as ftp:
                if attempt == 0:
                    try:
                        ftp.delete(f'/model/{filename}')
                        logger.info(f"🗑️  Cleared pre-existing remote file /model/{filename} to prevent resume collisions")
                    except Exception:
                        pass
                with open(filepath, 'rb') as f:
                    if uploaded_bytes > 0:
                        logger.info(f"🔄 Resuming from {uploaded_bytes // 1024}KB...")
                        f.seek(uploaded_bytes)
                    try:
                        if not getattr(args, "json", False):
                            from rich.progress import Progress, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn
                            progress = Progress(
                                "[progress.description]{task.description}",
                                "[progress.percentage]{task.percentage:>3.0f}%",
                                DownloadColumn(),
                                TransferSpeedColumn(),
                                TimeRemainingColumn(),
                                transient=True
                            )
                            progress.start()
                            task_id = progress.add_task(f"Uploading {filename}...", total=os.path.getsize(filepath))
                            progress.update(task_id, completed=uploaded_bytes)
                            def upload_callback(block):
                                progress.update(task_id, advance=len(block))
                        else:
                            progress = None
                            upload_callback = None
                    except ImportError:
                        progress = None
                        upload_callback = None

                    try:
                        ftp.storbinary(f'STOR /model/{filename}', f, blocksize=1048576, rest=uploaded_bytes if uploaded_bytes > 0 else None, callback=upload_callback)
                    finally:
                        if progress:
                            progress.stop()
                logger.info(f"✅ Uploaded {filename} to printer")
                if bool(_namespace_get(args, "json", False)):
                    emit_json({
                        "status": "uploaded",
                        "command": "upload",
                        "file": filepath,
                        "remote_name": filename,
                        "bytes": filesize,
                        "uploaded": True,
                    })
                return filename
        except Exception as e:
            # Try to determine how much was uploaded if possible
            logger.warning(f"⚠️  Upload attempt {attempt + 1} failed: {e}")
            if attempt < max_retries:
                start_wait = time.time()
                # Attempt to get size from printer to resume
                try:
                    with bambu.get_ftp(timeout=5) as ftp_check:
                        size = ftp_check.size(f'/model/{filename}')
                        remote_size = int(size) if size is not None else 0
                        if remote_size == filesize:
                            logger.info(f"✅ Uploaded {filename} to printer")
                            if bool(_namespace_get(args, "json", False)):
                                emit_json({
                                    "status": "uploaded",
                                    "command": "upload",
                                    "file": filepath,
                                    "remote_name": filename,
                                    "bytes": filesize,
                                    "uploaded": True,
                                    "verified_remote": True,
                                })
                            return filename
                        if 0 < remote_size < filesize:
                            uploaded_bytes = remote_size
                        else:
                            uploaded_bytes = 0
                except Exception:
                    # If we can't get size, we'll try to resume from where we were if it was a timeout
                    pass

                logger.info(f"   Retrying in {retry_delay}s...")
                elapsed = time.time() - start_wait
                remaining_delay = retry_delay - elapsed
                if remaining_delay > 0:
                    time.sleep(remaining_delay)
            else:
                total_attempts = max_retries + 1
                message = f"Upload failed after {total_attempts} attempts ({max_retries} retries)."
                logger.error(f"❌ {message}")
                emit_json_error(
                    args,
                    "upload",
                    EXIT_NETWORK_ERROR,
                    message,
                    failed_step="upload",
                    file=filepath,
                    remote_name=filename,
                    attempts=total_attempts,
                    retries=max_retries,
                )
                sys.exit(EXIT_NETWORK_ERROR)

def cmd_files(args):
    """List files on the printer."""
    from bambu_cli import bambu
    from bambu_cli.cli import _namespace_get
    from bambu_cli.utils import emit_json, emit_json_error, EXIT_NETWORK_ERROR
    from bambu_cli.protocols.ftps import get_ftp
    json_mode = bool(_namespace_get(args, "json", False))
    try:
        with get_ftp() as ftp:
            files = ftp.nlst('/model/')
        remote_files = [
            {"name": bambu._portable_basename(path), "path": path}
            for path in files
        ]
        if json_mode:
            emit_json({
                "status": "ok",
                "command": "files",
                "count": len(remote_files),
                "files": remote_files,
            })
            return
        if not files:
            logger.info("No files on printer.")
            return
        logger.info("📁 Files on printer:")
        for f in files:
            logger.info(f"   {f}")
    except Exception as e:
        message = f"Error listing files: {e}"
        logger.error(message)
        emit_json_error(args, "files", EXIT_NETWORK_ERROR, message, failed_step="ftps", files=[])
        sys.exit(EXIT_NETWORK_ERROR)

def cmd_print(args):
    """Start printing a file already on the printer."""
    from bambu_cli import bambu
    from bambu_cli.cli import _namespace_get
    from bambu_cli.utils import emit_json, emit_json_error
    from bambu_cli.cli import EXIT_FILE_ERROR, EXIT_COMMAND_ERROR
    
    dry_run = getattr(args, 'dry_run', False)
    basename = str(args.file or "")

    if bambu._safe_remote_name(basename) is None:
        message = f"Refusing to print file with unsafe name: {bambu._name_for_message(basename)!r}"
        logger.error(message)
        emit_json_error(args, "print", EXIT_FILE_ERROR, message, failed_step="validate", file=basename)
        sys.exit(EXIT_FILE_ERROR)
    if not bambu._is_print_ready_name(basename):
        message = bambu._print_ready_error_message(basename, "print")
        logger.error(message)
        emit_json_error(args, "print", EXIT_FILE_ERROR, message, failed_step="validate", file=basename)
        sys.exit(EXIT_FILE_ERROR)

    ams_mapping, print_option_error = bambu._parse_print_options(args)
    if print_option_error:
        logger.error(print_option_error)
        emit_json_error(args, "print", EXIT_COMMAND_ERROR, print_option_error, failed_step="validate", file=basename)
        sys.exit(EXIT_COMMAND_ERROR)

    if not args.confirm and not dry_run:
        logger.warning("⚠️  This will START a print. Add --confirm to proceed.")
        if bool(_namespace_get(args, "json", False)):
            emit_json({
                "status": "confirmation_required",
                "command": "print",
                "file": basename,
                "printed": False,
                "next_command": bambu._print_next_command(args, basename),
            })
        return

    payload = bambu.generate_print_payload(
        basename,
        use_ams=getattr(args, 'use_ams', False),
        ams_mapping=ams_mapping,
        timelapse=getattr(args, 'timelapse', False),
        bed_leveling=not getattr(args, 'skip_bed_leveling', False),
        flow_cali=not getattr(args, 'skip_flow_cali', False)
    )
    try:
        bambu._LAST_ERROR_PAYLOAD = None
        bambu.execute_print_command(payload, basename, dry_run=dry_run)
    except SystemExit as exc:
        exit_code = bambu._exit_code_from_system_exit(exc)
        detail = bambu._last_error_for("print")
        emit_json_error(
            args,
            "print",
            exit_code,
            detail.get("error") if detail else "print failed; see stderr for details",
            failed_step="dry_run" if dry_run else "print",
            file=basename,
            printed=False,
            dry_run=bool(dry_run),
            **({"print_error": detail} if detail else {}),
        )
        raise
    if bool(_namespace_get(args, "json", False)):
        emit_json({
            "status": "dry_run_ok" if dry_run else "print_started",
            "command": "print",
            "file": basename,
            "printed": not dry_run,
            "dry_run": bool(dry_run),
        })
    return basename

def cmd_download(args):
    """Download a model file from a remote URL."""
    from bambu_cli import bambu
    return bambu._cmd_download(args)

def cmd_delete(args):
    """Delete a file from the printer via FTPS."""
    from bambu_cli import bambu
    from bambu_cli.cli import _namespace_get
    from bambu_cli.utils import emit_json, emit_json_error
    from bambu_cli.cli import EXIT_FILE_ERROR, EXIT_COMMAND_ERROR, EXIT_NETWORK_ERROR
    from bambu_cli.protocols.ftps import get_ftp
    
    filename = str(args.file or "")
    if bambu._safe_remote_name(filename) is None:
        message = f"Refusing to delete file with unsafe name: {bambu._name_for_message(filename)!r}"
        logger.error(message)
        emit_json_error(args, "delete", EXIT_FILE_ERROR, message, failed_step="validate", file=filename, deleted=False)
        sys.exit(EXIT_FILE_ERROR)
    if not args.confirm:
        logger.warning(f"⚠️  This will DELETE '{filename}' from the printer. Add --confirm to proceed.")
        if bool(_namespace_get(args, "json", False)):
            emit_json({
                "status": "confirmation_required",
                "command": "delete",
                "file": filename,
                "deleted": False,
                "next_command": ["delete", filename, "--confirm", "--json"],
            })
        sys.exit(EXIT_COMMAND_ERROR)

    try:
        with get_ftp() as ftp:
            ftp.delete(f'/model/{filename}')
        logger.info(f"🗑️  Deleted {filename} from printer")
        if bool(_namespace_get(args, "json", False)):
            emit_json({
                "status": "deleted",
                "command": "delete",
                "file": filename,
                "deleted": True,
            })
    except Exception as e:
        message = f"Delete failed: {e}"
        logger.error(message)
        emit_json_error(args, "delete", EXIT_NETWORK_ERROR, message, failed_step="ftps", file=filename, deleted=False)
        sys.exit(EXIT_NETWORK_ERROR)

def cmd_snapshot(args):
    """Capture a camera snapshot using the RTSP Streamer Docker container."""
    from bambu_cli import bambu
    bambu._cmd_snapshot(args)

def cmd_preflight(args):
    """Check local install/config readiness without contacting printer."""
    from bambu_cli import bambu
    bambu._cmd_preflight(args)

def cmd_job(args):
    """One-shot URL/local file workflow: download, slice, upload, optionally print."""
    from bambu_cli import bambu
    return bambu._cmd_job(args)

def cmd_gcode(args):
    """Send raw G-code to the printer via MQTT."""
    from bambu_cli.cli import _namespace_get
    from bambu_cli.utils import emit_json, emit_json_error, EXIT_NETWORK_ERROR
    from bambu_cli.protocols.mqtt import send_command
    gcode = args.code
    payload = json.dumps({
        "print": {
            "sequence_id": get_sequence_id(),
            "command": "gcode_line",
            "param": gcode
        }
    })
    if not send_command(payload):
        message = "Failed to send G-code command."
        logger.error(message)
        emit_json_error(args, "gcode", EXIT_NETWORK_ERROR, message, failed_step="mqtt", gcode=gcode, sent=False)
        sys.exit(EXIT_NETWORK_ERROR)
    logger.info(f"📡 Sent: {gcode}")
    if bool(_namespace_get(args, "json", False)):
        emit_json({
            "status": "sent",
            "command": "gcode",
            "gcode": gcode,
            "sent": True,
        })

def cmd_status(args):
    """Query and display the printer's current status."""
    from bambu_cli.cli import _namespace_get
    from bambu_cli.utils import emit_json, emit_json_error, EXIT_NETWORK_ERROR
    from bambu_cli.protocols.mqtt import get_status
    from bambu_cli.protocols.mqtt import monitor_status
    if bool(_namespace_get(args, "monitor", False)):
        monitor_status(args)
        return

    data = get_status()
    if not data:
        message = "Could not connect to printer."
        logger.error(message)
        emit_json_error(args, "status", EXIT_NETWORK_ERROR, message, failed_step="mqtt")
        sys.exit(EXIT_NETWORK_ERROR)

    if args.json:
        payload = {
            "status": "ok",
            "command": "status",
            "printer": data,
        }
        payload.update({k: v for k, v in data.items() if k not in ("status", "command")})
        emit_json(payload)
        return

    state = data.get("gcode_state", "UNKNOWN")
    pct = data.get("mc_percent", 0)
    layer = data.get("layer_num", 0)
    total_layers = data.get("total_layer_num", 0)
    try:
        remaining = int(data.get("mc_remaining_time", 0))
    except (TypeError, ValueError):
        remaining = 0
    filename = data.get("gcode_file", "")
    bed_temp = data.get("bed_temper", "?")
    bed_target = data.get("bed_target_temper", "?")
    nozzle_temp = data.get("nozzle_temper", "?")
    nozzle_target = data.get("nozzle_target_temper", "?")
    fan = data.get("cooling_fan_speed", "?")
    wifi = str(data.get("wifi_signal", "?")).replace("dBm", "")

    logger.info(f"🖨️  Bambu Printer Status")
    logger.info(f"   State: {state}")
    if state == "RUNNING":
        hrs, mins = divmod(remaining, 60)
        logger.info(f"   File: {filename}")
        logger.info(f"   Progress: {pct}% | Layer {layer}/{total_layers}")
        logger.info(f"   Time left: {hrs}h {mins}m")
    logger.info(f"   Bed: {bed_temp}°C / {bed_target}°C")
    logger.info(f"   Nozzle: {nozzle_temp}°C / {nozzle_target}°C")
    logger.info(f"   Fan: {fan} | WiFi: {wifi}dBm")
