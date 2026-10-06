"""Account validation, date formatting, and user-info presentation."""

from datetime import datetime, timezone


def get_live_categories(server, username, password, timeout=20):
    """Retrieve and validate the live TV category list for this account."""
    # Import here because the connection module also calls this app's user validator.
    # The connection module owns HTTP; this method owns category validation.
    from startshare_connection import request_live_categories

    categories = request_live_categories(server, username, password, timeout)
    if not isinstance(categories, list) or any(
        not isinstance(category, dict)
        or "category_id" not in category
        or "category_name" not in category
        for category in categories
    ):
        raise ValueError("Server response does not contain a valid live TV category list.")
    return categories


def get_movies_categories(server, username, password, timeout=20):
    """Retrieve and validate the video-on-demand movie categories for this account."""
    # Keep HTTP in the connection module; import locally to avoid circular imports.
    from startshare_connection import request_movies_categories

    categories = request_movies_categories(server, username, password, timeout)
    # An empty list is valid when the account has no available movie categories.
    if not isinstance(categories, list) or any(
        not isinstance(category, dict)
        or "category_id" not in category
        or "category_name" not in category
        for category in categories
    ):
        raise ValueError("Server response does not contain a valid movie category list.")
    return categories


def get_series_categories(server, username, password, timeout=20):
    """Retrieve and validate the video-on-demand series categories for this account."""
    # Keep HTTP in the connection module; import locally to avoid circular imports.
    from startshare_connection import request_series_categories

    categories = request_series_categories(server, username, password, timeout)
    # Empty lists are valid; each returned category must have an ID and name.
    if not isinstance(categories, list) or any(
        not isinstance(category, dict)
        or "category_id" not in category
        or "category_name" not in category
        for category in categories
    ):
        raise ValueError("Server response does not contain a valid series category list.")
    return categories


def get_category_items(server, username, password, category_type, category_id, timeout=20):
    """Return the validated content list for a selected category."""
    from startshare_connection import request_category_items

    items = request_category_items(server, username, password, category_type, category_id, timeout)
    id_key = "series_id" if category_type == "Series" else "stream_id"
    if not isinstance(items, list) or any(
        not isinstance(item, dict) or "name" not in item or id_key not in item
        for item in items
    ):
        raise ValueError("Server response does not contain a valid category content list.")
    return items


def get_movie_info(server, username, password, movie_id, timeout=20):
    """Fetch a movie's metadata; missing optional info is allowed."""
    from startshare_connection import request_movie_info

    data = request_movie_info(server, username, password, movie_id, timeout)
    if not isinstance(data, dict) or not isinstance(data.get("movie_data"), dict):
        raise ValueError("Server response does not contain valid movie details.")
    if not data.get("info"):
        data["info"] = {}
    if not isinstance(data["info"], dict):
        raise ValueError("Server returned invalid movie metadata.")
    return data


def get_series_info(server, username, password, series_id, timeout=20):
    """Retrieve series metadata and episodes grouped by season."""
    from startshare_connection import request_series_info

    data = request_series_info(server, username, password, series_id, timeout)
    if not isinstance(data, dict) or not isinstance(data.get("info"), dict):
        raise ValueError("Server response does not contain valid series details.")
    episodes = data.get("episodes", {})
    # Some servers encode an empty episode collection as an empty JSON list.
    if episodes == []:
        episodes = {}
    if not isinstance(episodes, dict) or any(
        not isinstance(season, list) or any(
            not isinstance(episode, dict) or "id" not in episode for episode in season
        ) for season in episodes.values()
    ):
        raise ValueError("Server returned invalid series episodes.")
    data["episodes"] = episodes
    return data


def print_live_categories(categories):
    """Display category IDs and names, including an empty-list message."""
    print("\nLive TV categories:")
    if not categories:
        print("No live TV categories available.")
    for category in categories:
        print(f"{category['category_id']}: {category['category_name']}")


def get_user_info(data):
    """Validate the connected server's response and remove the account password."""
    # The connection module already fetched JSON; this function makes no request.
    if not isinstance(data, dict) or not isinstance(data.get("user_info"), dict):
        raise ValueError("Server response does not contain a user_info object.")
    # A successful HTTP response can still contain rejected credentials.
    # Normalize auth because servers may return either integer 1 or string "1".
    if str(data["user_info"].get("auth")) != "1":
        raise ValueError("Authentication failed. Check your account credentials.")
    # Remove the password in place before either summary or JSON output uses data.
    data["user_info"].pop("password", None)
    return data


def format_date(value):
    """Convert Unix seconds to a readable UTC date, tolerating missing values."""
    # Treat absent or zero timestamps as unspecified rather than January 1970.
    if value in (None, "", "0", 0):
        return "Not provided"
    try:
        # UTC gives consistent output regardless of the computer's local timezone.
        return datetime.fromtimestamp(int(value), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, TypeError, OverflowError, OSError):
        return "Invalid timestamp"


def print_user_info(data):
    """Display the account summary."""
    # Called by main after get_user_info has validated the response structure.
    user = data["user_info"]
    # Optional fields may be absent even in a valid account response.
    for label, key in (("Username", "username"), ("Status", "status"),
                       ("Active connections", "active_cons"), ("Maximum connections", "max_connections")):
        print(f"{label}: {user.get(key, 'Not provided')}")
    print(f"Expires: {format_date(user.get('exp_date'))}")
    print(f"Created: {format_date(user.get('created_at'))}")
    print(f"Trial: { {'0': 'No', '1': 'Yes'}.get(str(user.get('is_trial')), 'Not provided') }")


