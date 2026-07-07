"""Shared immutable constants for bambu-cli.

Single source of truth for exit codes, file-type tables, safety limits, and
default timeouts. Mutable runtime state (printer address, simulation flag,
loaded config) lives in ``bambu_cli.bambu``.
"""

VERSION = "0.1.0"

# Exit codes
EXIT_SUCCESS = 0
EXIT_CONFIG_ERROR = 1
EXIT_NETWORK_ERROR = 2
EXIT_FILE_ERROR = 3
EXIT_PRINTER_ERROR = 4
EXIT_COMMAND_ERROR = 5
EXIT_TIMEOUT = 6

# Default timeouts (seconds); override per-run via CLI flags or config keys.
DEFAULT_NETWORK_TIMEOUT = 15.0
DOWNLOAD_TIMEOUT = 60.0
SLICER_TIMEOUT = 120.0
COMMAND_TIMEOUT = 5.0
PRINT_ACK_TIMEOUT = 10.0
UPLOAD_TIMEOUT = 300.0

# Download safety limits
HTML_LINK_SCAN_LIMIT = 1024 * 1024
DEFAULT_MAX_DOWNLOAD_MB = 2048
MAX_DOWNLOAD_FILENAME_LENGTH = 160
DNS_CACHE_TTL = 300

# File-type tables
BED_PLATE_TYPES = ['cool_plate_temp', 'hot_plate_temp', 'textured_plate_temp', 'eng_plate_temp']
SLICEABLE_EXTENSIONS = ('.stl', '.step', '.stp', '.obj')
PRINT_READY_EXTENSIONS = ('.3mf', '.gcode')
DOWNLOADABLE_EXTENSIONS = SLICEABLE_EXTENSIONS + PRINT_READY_EXTENSIONS
ARCHIVE_DOWNLOAD_EXTENSIONS = ('.zip',)
DOWNLOAD_CANDIDATE_EXTENSIONS = DOWNLOADABLE_EXTENSIONS + ARCHIVE_DOWNLOAD_EXTENSIONS
DOWNLOAD_LINK_EXTENSION_PRIORITY = {
    ".stl": 0,
    ".step": 1,
    ".stp": 1,
    ".obj": 2,
    ".3mf": 3,
    ".gcode": 4,
    ".zip": 5,
}
KNOWN_UNSUPPORTED_DOWNLOAD_EXTENSIONS = {
    ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
    ".pdf", ".txt",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
}
KNOWN_UNSUPPORTED_CONTENT_TYPES = {
    "application/json",
    "application/pdf",
    "application/x-7z-compressed",
    "application/x-bzip2",
    "application/x-gzip",
    "application/x-rar-compressed",
    "application/x-tar",
    "text/csv",
    "text/plain",
    "text/xml",
}
WINDOWS_RESERVED_FILENAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# Command routing sets
PRINTER_CONFIG_COMMANDS = {
    "status", "light", "pause", "resume", "stop", "upload", "files",
    "print", "job", "send", "delete", "snapshot", "gcode", "doctor",
}
LOCAL_COMMANDS = {"slice", "download", "preflight", "setup"}
PRINTER_NETWORK_COMMANDS = PRINTER_CONFIG_COMMANDS - LOCAL_COMMANDS

# Camera defaults
CAMERA_CONTAINER_NAME = "bambu_camera"
CAMERA_DEFAULT_IMAGE = "bambu_p1_streamer"
CAMERA_DEFAULT_PORT = "1985:1984"
