"""HTTP connection to a Startshare Xtream-compatible server."""

import json
import math
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import startshare_app

# Content lists include metadata for every title and can exceed the smaller
# account/category response limit even when filtered to one category.
API_RESPONSE_LIMIT = 2_000_000
CONTENT_RESPONSE_LIMIT = 50_000_000
CONTENT_ACTIONS = {"get_live_streams", "get_vod_streams", "get_series", "get_series_info"}


def connect(server, username, password, timeout=20):
    """Connect to the server, then pass its response to the app for validation.

    A failed request raises ValueError before the app is called. The account API
    supplies user info in the same request, so no separate probe is needed.
    """
    # Fetch first. If this raises an error, the app method below is never called.
    data = request_user_info(server, username, password, timeout)
    # A reachable server still needs account authentication checked by the app.
    return startshare_app.get_user_info(data)


def api_url(server):
    """Accept a server base URL or a full player_api.php endpoint."""
    parts = urlsplit(server.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Server must be a valid http:// or https:// URL.")
    # Credentials are added separately; the configured URL identifies the endpoint.
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Provide a server URL without credentials, query, or fragment.")
    try:
        # Accessing .port makes urllib validate its syntax and range.
        parts.port
    except ValueError:
        raise ValueError("Server URL contains an invalid port.") from None
    # Preserve any server path prefix and avoid adding the endpoint twice.
    path = parts.path.rstrip("/")
    if not path.endswith("/player_api.php"):
        path += "/player_api.php"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def request_user_info(server, username, password, timeout=20):
    """Request and decode account information from the Startshare server."""
    return request_api(server, username, password, timeout)


def request_live_categories(server, username, password, timeout=20):
    """Fetch live TV categories using the Xtream player API action."""
    return request_api(server, username, password, timeout, action="get_live_categories")


def request_movies_categories(server, username, password, timeout=20):
    """Fetch movie categories using the Xtream video-on-demand action."""
    return request_api(server, username, password, timeout, action="get_vod_categories")


def request_series_categories(server, username, password, timeout=20):
    """Fetch video-on-demand series categories using the Xtream player API."""
    return request_api(server, username, password, timeout, action="get_series_categories")


def request_category_items(server, username, password, category_type, category_id, timeout=20):
    """Fetch only the selected category's channels, movies, or series."""
    actions = {"Live TV": "get_live_streams", "Movies": "get_vod_streams", "Series": "get_series"}
    if category_type not in actions or not str(category_id).strip():
        raise ValueError("A valid category type and ID are required.")
    return request_api(server, username, password, timeout,
                       action=actions[category_type], category_id=category_id)


def request_movie_info(server, username, password, movie_id, timeout=20):
    return request_api(server, username, password, timeout, action="get_vod_info", vod_id=movie_id)


def request_series_info(server, username, password, series_id, timeout=20):
    return request_api(server, username, password, timeout, action="get_series_info", series_id=series_id)


def series_stream_url(server, username, password, episode_id, extension):
    return movie_stream_url(server, username, password, episode_id, extension, stream_type="series")


def movie_stream_url(server, username, password, movie_id, extension, stream_type="movie"):
    """Build the provider's authenticated movie URL without logging it."""
    if not str(movie_id).isdigit() or not str(extension).isalnum():
        raise ValueError("Movie ID or file extension is invalid.")
    base = api_url(server).rsplit("/player_api.php", 1)[0]
    return f"{base}/{stream_type}/{quote(username, safe='')}/{quote(password, safe='')}/{movie_id}.{extension}"


def request_image(url, timeout=20):
    """Download artwork with a size limit; credentials are not added to this URL."""
    if urlsplit(url).scheme not in ("http", "https"):
        raise ValueError("Artwork URL must use HTTP or HTTPS.")
    try:
        with urlopen(Request(url, headers={"User-Agent": "IPTV-Account-Info/1.0"}), timeout=timeout) as response:
            raw = response.read(10_000_001)
        if len(raw) > 10_000_000:
            raise ValueError("Artwork exceeds the download limit.")
        return raw
    except (URLError, OSError):
        raise ValueError("Artwork could not be downloaded.") from None


def request_api(server, username, password, timeout=20, action=None, category_id=None, vod_id=None, series_id=None):
    """Send an authenticated player API request and decode its JSON response."""
    # Reject invalid inputs before attempting a network connection.
    if not username or not password:
        raise ValueError("Username and password are required.")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout must be a positive finite number.")
    # Xtream returns account info when no action is supplied. urlencode handles
    # special characters in credentials; this credential-bearing URL is not logged.
    params = {"username": username, "password": password}
    if action is not None:
        params["action"] = action
    if category_id is not None:
        params["category_id"] = category_id
    if vod_id is not None:
        params["vod_id"] = vod_id
    if series_id is not None:
        params["series_id"] = series_id
    url = api_url(server) + "?" + urlencode(params)
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "IPTV-Account-Info/1.0"})
    response_limit = CONTENT_RESPONSE_LIMIT if action in CONTENT_ACTIONS else API_RESPONSE_LIMIT
    try:
        # urlopen performs the HTTP request; the context manager closes the response.
        with urlopen(request, timeout=timeout) as response:
            # Read one extra byte to detect oversized data without truncating JSON.
            raw = response.read(response_limit + 1)
        if len(raw) > response_limit:
            raise ValueError(f"Server response exceeds the {response_limit / 1_000_000:g} MB API response limit.")
        # Decode response bytes and parse JSON. Account validation belongs to the app.
        data = json.loads(raw.decode("utf-8-sig"))
    except HTTPError as error:
        # Expose the HTTP status without including the URL containing credentials.
        raise ValueError(f"Server returned HTTP {error.code}.") from None
    except (URLError, TimeoutError, OSError):
        raise ValueError("Could not reach the server. Check the URL, connection, and timeout.") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Server did not return JSON. Check that it supports the Xtream player API.") from None
    return data


