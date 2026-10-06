"""Retrieve account details from a Starshare/Startshare Xtream-compatible server.

Run: python main.py
Use --cli for terminal output, or --json for JSON output.
Loads config.json beside this script, or the file selected with --config.
Credentials are read exclusively from the config file; no input is prompted for.
Movie artwork and embedded playback require Pillow, python-vlc, and VLC installed.
"""

import argparse
import json
from pathlib import Path
import sys

from startshare_app import get_live_categories, print_live_categories, print_user_info
from startshare_connection import api_url, connect


def load_config(path):
    """Load required account settings without exposing their values in errors."""
    try:
        # utf-8-sig accepts JSON saved with or without a UTF-8 byte-order mark.
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except OSError:
        raise ValueError(f"Could not read config file: {path}") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Config file must contain valid UTF-8 JSON.") from None
    if not isinstance(data, dict):
        raise ValueError("Config file must contain a JSON object.")
    # Keep numeric-looking credentials as strings to preserve leading zeros.
    for key in ("server", "username", "password"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"Config '{key}' must be a nonempty string.")
    return data


def main():
    """Resolve settings, connect to the server, and display the validated result."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, help="Config file (default: config.json beside this script)")
    parser.add_argument("--timeout", type=float, default=20, help="Request timeout in seconds (default: 20)")
    parser.add_argument("--cli", action="store_true", help="Use terminal output instead of the graphical interface")
    parser.add_argument("--json", action="store_true", help="Print account info and live categories as JSON, without the account password")
    args = parser.parse_args()
    try:
        # Locate the default config beside main.py, regardless of working directory.
        config_path = args.config or Path(__file__).resolve().with_name("config.json")
        config = load_config(config_path)
        server = config["server"].strip()
        username = config["username"]
        password = config["password"]
        api_url(server)
        # The GUI automatically connects using these validated config settings.
        if not args.cli and not args.json:
            from startshare_ui import launch_ui

            launch_ui(
                server=server,
                username=username,
                password=password,
                timeout=args.timeout,
            )
            return 0
        # Flow: connect -> request_user_info (HTTP) -> get_user_info (validation).
        data = connect(server, username, password, args.timeout)
        # Both output modes receive data with the account password removed.
        if args.json:
            # Keep JSON output as one document, retaining the existing account keys.
            data["live_categories"] = get_live_categories(server, username, password, args.timeout)
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print_user_info(data)
            # Retrieve categories only after authenticating and printing account info.
            categories = get_live_categories(server, username, password, args.timeout)
            print_live_categories(categories)
        return 0
    except (ValueError, EOFError) as error:
        # Report expected failures without a traceback; signal failure to the shell.
        print(f"Error: {error or 'Missing input.'}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    # Importing this module does not run the app; executing it does.
    sys.exit(main())
