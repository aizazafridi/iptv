"""Tkinter panels for connecting and browsing live TV, movie, and series categories."""

from queue import Empty, Queue
from threading import Thread
from io import BytesIO
import sys
import tkinter as tk
from tkinter import ttk

from startshare_app import format_date, get_category_items, get_live_categories, get_movies_categories, get_series_categories, get_movie_info, get_series_info
from startshare_connection import connect, request_image, movie_stream_url, series_stream_url


class StartshareUI:
    def __init__(self, root, server="", username="", password="", timeout=20):
        self.root = root
        self.timeout = timeout
        self.credentials = (server, username, password)
        self.results = Queue()
        self.busy = False
        self.view_id = 0
        self.account_data = None
        self.player = None
        self.vlc_instance = None
        self.poster_photo = None
        self.fullscreen = False
        root.bind("<Escape>", self.exit_fullscreen)
        root.bind("<F11>", self.toggle_fullscreen)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.status = tk.StringVar(value="Connecting...")
        root.title("Startshare IPTV")
        root.geometry("1000x600")
        root.minsize(800, 380)
        self.panel = ttk.Frame(root, padding=24)
        self.panel.pack(fill="both", expand=True)
        self.show_connection_panel()
        # Poll worker results on the GUI thread: workers never access Tk widgets.
        root.after(100, self.poll_results)
        # Start after Tk has had a chance to display the loading view.
        root.after(0, self.connect_to_server)

    def clear_panel(self):
        self.stop_playback()
        self.poster_photo = None
        # Ignore responses from a view the user has left, including pending loads.
        self.view_id += 1
        self.busy = False
        for widget in self.panel.winfo_children():
            widget.destroy()

    def show_connection_panel(self):
        self.clear_panel()
        ttk.Label(self.panel, text="Startshare IPTV", font=("Segoe UI", 18)).pack(anchor="w", pady=(0, 20))
        # Retry reuses config credentials without asking the user to enter them.
        self.action_button = ttk.Button(self.panel, text="Retry", command=self.connect_to_server)
        self.action_button.pack(anchor="w", pady=8)
        self.request_buttons = [self.action_button]
        ttk.Label(self.panel, textvariable=self.status, wraplength=460).pack(anchor="w", pady=12)

    def run_request(self, operation, on_success, loading_message):
        """Run network work in a daemon thread so slow requests do not freeze Tk."""
        if self.busy:
            return
        self.busy = True
        view_id = self.view_id
        # Disable all request buttons until the current request finishes.
        for button in self.request_buttons:
            button.state(["disabled"])
        self.status.set(loading_message)

        def worker():
            try:
                result = operation()
            except ValueError as error:
                self.results.put((view_id, on_success, None, str(error)))
            except Exception:
                # Avoid exposing credentials through unexpected exception messages.
                self.results.put((view_id, on_success, None, "Unexpected error while contacting the server. Please retry."))
            else:
                self.results.put((view_id, on_success, result, None))

        Thread(target=worker, daemon=True).start()

    def poll_results(self):
        """Apply completed requests to the current panel on the GUI thread."""
        try:
            view_id, callback, data, error = self.results.get_nowait()
        except Empty:
            pass
        else:
            if view_id == self.view_id:
                self.busy = False
                for button in self.request_buttons:
                    button.state(["!disabled"])
                if error:
                    self.status.set(error)
                else:
                    callback(data)
        self.root.after(100, self.poll_results)

    def connect_to_server(self):
        """Authenticate automatically using the credentials loaded from config."""
        self.run_request(
            lambda: connect(*self.credentials, timeout=self.timeout),
            self.show_account_panel,
            "Connecting...",
        )

    def show_account_panel(self, data):
        """Switch panels only after the server response passes authentication."""
        self.clear_panel()
        self.account_data = data
        user = data["user_info"]
        ttk.Label(self.panel, text="Startshare IPTV", font=("Segoe UI", 18)).pack(anchor="w")
        ttk.Label(self.panel, text=f"Account: {user.get('username', self.credentials[1])}   |   Status: {user.get('status', 'Unknown')}").pack(anchor="w", pady=(10, 4))
        ttk.Label(self.panel, text=f"Expires: {format_date(user.get('exp_date'))}").pack(anchor="w")
        buttons_panel = ttk.Frame(self.panel)
        buttons_panel.pack(anchor="w", pady=16)
        self.action_button = ttk.Button(buttons_panel, text="LiveTV", command=self.live_tv_clicked)
        self.action_button.pack(side="left")
        self.movies_button = ttk.Button(buttons_panel, text="Movies", command=self.movies_clicked)
        self.movies_button.pack(side="left", padx=(8, 0))
        self.series_button = ttk.Button(buttons_panel, text="Series", command=self.series_clicked)
        self.series_button.pack(side="left", padx=(8, 0))
        self.request_buttons = [self.action_button, self.movies_button, self.series_button]
        self.status.set("Connected. Press LiveTV, Movies, or Series to view categories.")
        ttk.Label(self.panel, textvariable=self.status, wraplength=460).pack(anchor="w", pady=(0, 12))

    def open_categories_view(self, category_type, fetch_categories, cached=False):
        """Open a dedicated view and load its list without blocking navigation."""
        self.clear_panel()
        self.category_type = category_type
        toolbar = ttk.Frame(self.panel)
        toolbar.pack(fill="x", pady=(0, 16))
        # Back stays enabled while loading and restores the saved account data.
        ttk.Button(toolbar, text="Back", command=self.back_to_main).pack(side="left")
        ttk.Label(toolbar, text=f"{category_type} categories", font=("Segoe UI", 18)).pack(side="left", padx=16)
        self.action_button = ttk.Button(
            toolbar, text="Refresh", command=lambda: self.load_categories(category_type, fetch_categories)
        )
        self.action_button.pack(side="right")
        self.request_buttons = [self.action_button]
        ttk.Label(self.panel, textvariable=self.status, wraplength=460).pack(anchor="w", pady=(0, 12))
        # Keep the category list narrow and anchored to the left as the window grows.
        content_panel = ttk.Frame(self.panel)
        content_panel.pack(fill="both", expand=True)
        table_panel = ttk.Frame(content_panel, width=320)
        table_panel.pack(side="left", fill="y", anchor="nw")
        table_panel.pack_propagate(False)
        self.categories = ttk.Treeview(table_panel, columns=("id", "name"), show="headings", selectmode="browse")
        self.categories.bind("<<TreeviewSelect>>", self.category_selected)
        self.categories.heading("id", text="Category ID")
        self.categories.heading("name", text="Category")
        self.categories.column("id", width=85, minwidth=85, stretch=False)
        self.categories.column("name", width=210, minwidth=120)
        scrollbar = ttk.Scrollbar(table_panel, orient="vertical", command=self.categories.yview)
        self.categories.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.categories.pack(side="left", fill="both", expand=True)
        items_panel = ttk.Frame(content_panel, padding=(16, 0, 0, 0))
        items_panel.pack(side="left", fill="both", expand=True)
        self.items_title = tk.StringVar(value="Select a category to view its contents.")
        ttk.Label(items_panel, textvariable=self.items_title, wraplength=420).pack(anchor="w", pady=(0, 10))
        self.items = ttk.Treeview(items_panel, columns=("id", "name"), show="headings")
        self.items.bind("<Double-1>", self.movie_double_clicked)
        self.items.heading("id", text="ID")
        self.items.heading("name", text="Title / Channel")
        self.items.column("id", width=85, stretch=False)
        self.items.column("name", width=350)
        items_scrollbar = ttk.Scrollbar(items_panel, orient="vertical", command=self.items.yview)
        self.items.configure(yscrollcommand=items_scrollbar.set)
        items_scrollbar.pack(side="right", fill="y")
        self.items.pack(side="left", fill="both", expand=True)
        if cached:
            self.show_categories(self.category_list, category_type)
            self.show_category_items(self.movie_browser_items, category_type, self.movie_browser_name)
        else:
            self.load_categories(category_type, fetch_categories)

    def back_to_main(self):
        """Return to the account view without reconnecting to the server."""
        self.show_account_panel(self.account_data)

    def load_categories(self, category_type, fetch_categories):
        self.run_request(
            lambda: fetch_categories(*self.credentials, timeout=self.timeout),
            lambda categories: self.show_categories(categories, category_type),
            f"Loading {category_type} categories...",
        )

    def live_tv_clicked(self):
        self.open_categories_view("Live TV", get_live_categories)

    def movies_clicked(self):
        self.open_categories_view("Movies", get_movies_categories)

    def series_clicked(self):
        self.open_categories_view("Series", get_series_categories)

    def show_categories(self, categories, category_type="Live TV"):
        self.category_list = categories
        # Replace the shared table only after the selected request succeeds.
        self.categories.heading("name", text=f"{category_type} category")
        self.categories.delete(*self.categories.get_children())
        self.items.delete(*self.items.get_children())
        self.items_title.set("Select a category to view its contents.")
        for category in categories:
            self.categories.insert("", "end", values=(category["category_id"], category["category_name"]))
        self.status.set(f"{category_type}: {len(categories)} categories." if categories else f"{category_type}: no categories available.")

    def category_selected(self, event=None):
        """Load selected category content; newer selections supersede old requests."""
        selection = self.categories.selection()
        if not selection:
            return
        category_id, category_name = self.categories.item(selection[0], "values")
        category_type = self.category_type
        # The previous request may finish later; its result must not replace this list.
        self.view_id += 1
        self.busy = False
        self.items.delete(*self.items.get_children())
        self.items_title.set(f"{category_name} — loading...")
        self.run_request(
            lambda: get_category_items(*self.credentials, category_type, category_id, timeout=self.timeout),
            lambda items: self.show_category_items(items, category_type, category_name),
            f"Loading {category_name}...",
        )

    def show_category_items(self, items, category_type, category_name):
        self.displayed_items = items
        self.displayed_category_name = category_name
        self.items.delete(*self.items.get_children())
        id_key = "series_id" if category_type == "Series" else "stream_id"
        for item in items:
            self.items.insert("", "end", values=(item[id_key], item["name"]))
        self.items_title.set(category_name)
        self.status.set(f"{category_name}: {len(items)} items." if items else f"{category_name}: no items available.")

    def movie_double_clicked(self, event):
        """Movie and series rows open details; ignore empty space and live channels."""
        if self.category_type not in ("Movies", "Series") or self.busy:
            return
        row = self.items.identify_row(event.y)
        if not row:
            return
        movie_id = str(self.items.item(row, "values")[0])
        id_key = 'series_id' if self.category_type == 'Series' else 'stream_id'
        movie = next((item for item in self.displayed_items if str(item[id_key]) == movie_id), None)
        if movie is None:
            return
        self.movie_browser_items = self.displayed_items
        self.movie_browser_name = self.displayed_category_name
        self.selected_movie = movie
        self.details_type = self.category_type
        if self.details_type == 'Series':
            self.open_series_details()
            return
        self.open_movie_details()

    def back_to_movies(self):
        fetch = get_series_categories if self.details_type == 'Series' else get_movies_categories
        self.open_categories_view(self.details_type, fetch, cached=True)

    def open_series_details(self):
        self.clear_panel()
        ttk.Button(self.panel, text="Back", command=self.back_to_movies).pack(anchor="w")
        ttk.Label(self.panel, text=self.selected_movie['name'], font=("Segoe UI", 18)).pack(anchor="w", pady=12)
        self.action_button = ttk.Button(self.panel, text="Retry details", command=self.load_series_details)
        self.action_button.pack(anchor="w")
        self.request_buttons = [self.action_button]
        ttk.Label(self.panel, textvariable=self.status, wraplength=700).pack(anchor="w", pady=8)
        self.details_body = ttk.Frame(self.panel)
        self.details_body.pack(fill="both", expand=True)
        self.load_series_details()

    def load_series_details(self):
        series_id = self.selected_movie['series_id']

        def fetch():
            details = get_series_info(*self.credentials, series_id, timeout=self.timeout)
            image_url = details['info'].get('cover') or self.selected_movie.get('cover')
            artwork = None
            if image_url:
                try:
                    artwork = request_image(image_url, self.timeout)
                except ValueError:
                    pass
            return details, artwork

        self.run_request(fetch, self.show_movie_details, "Loading series details...")

    def open_movie_details(self):
        self.clear_panel()
        ttk.Button(self.panel, text="Back", command=self.back_to_movies).pack(anchor="w")
        ttk.Label(self.panel, text=self.selected_movie['name'], font=("Segoe UI", 18)).pack(anchor="w", pady=12)
        self.action_button = ttk.Button(self.panel, text="Retry details", command=self.load_movie_details)
        self.action_button.pack(anchor="w")
        self.request_buttons = [self.action_button]
        ttk.Label(self.panel, textvariable=self.status, wraplength=700).pack(anchor="w", pady=8)
        self.details_body = ttk.Frame(self.panel)
        self.details_body.pack(fill="both", expand=True)
        self.load_movie_details()

    def load_movie_details(self):
        movie_id = self.selected_movie['stream_id']

        def fetch():
            details = get_movie_info(*self.credentials, movie_id, timeout=self.timeout)
            image_url = details['info'].get('movie_image') or details['info'].get('cover_big') or self.selected_movie.get('stream_icon')
            image_bytes = None
            if image_url:
                try:
                    image_bytes = request_image(image_url, self.timeout)
                except ValueError:
                    pass  # Artwork failure must not prevent reading info or playing.
            return details, image_bytes

        self.run_request(fetch, self.show_movie_details, "Loading movie details...")

    def show_movie_details(self, result):
        from PIL import Image, ImageTk

        details, image_bytes = result
        self.movie_details = details
        for widget in self.details_body.winfo_children():
            widget.destroy()
        poster = ttk.Label(self.details_body, text="Artwork unavailable", width=28)
        poster.pack(side="left", anchor="n", padx=(0, 20))
        if image_bytes:
            try:
                with Image.open(BytesIO(image_bytes)) as image:
                    image.thumbnail((220, 330))
                    self.poster_photo = ImageTk.PhotoImage(image.copy())
                poster.configure(image=self.poster_photo, text="")
            except (OSError, ValueError, Image.DecompressionBombError):
                pass
        info_panel = ttk.Frame(self.details_body)
        info_panel.pack(side="left", fill="both", expand=True)
        info = details['info']
        text = tk.Text(info_panel, wrap="word", height=12, borderwidth=0)
        text.pack(fill="both", expand=True)
        lines = [f"{label}: {info.get(key) or 'Not provided'}" for label, key in (
            ('Genre', 'genre'), ('Release date', 'releasedate'), ('Rating', 'rating'),
            ('Duration', 'duration'), ('Director', 'director'), ('Cast', 'cast'))]
        text.insert('1.0', '\n'.join(lines) + '\n\n' + str(info.get('plot') or info.get('description') or 'No synopsis available.'))
        text.configure(state="disabled")
        if self.details_type == 'Series':
            self.episode_seasons = details['episodes']
            seasons = sorted(self.episode_seasons, key=lambda key: (0, int(key)) if str(key).isdigit() else (1, str(key)))
            seasons = [season for season in seasons if self.episode_seasons[season]]
            ttk.Label(info_panel, text="Season").pack(anchor="w")
            self.season_picker = ttk.Combobox(info_panel, values=seasons, state="readonly")
            self.season_picker.pack(fill="x", pady=4)
            self.season_picker.bind('<<ComboboxSelected>>', self.update_episode_picker)
            ttk.Label(info_panel, text="Episode").pack(anchor="w")
            self.episode_picker = ttk.Combobox(info_panel, state="readonly")
            self.episode_picker.pack(fill="x", pady=4)
            self.episode_play_button = ttk.Button(info_panel, text="Play", command=self.play_series_episode)
            self.episode_play_button.pack(anchor="w", pady=12)
            if seasons:
                self.season_picker.current(0)
                self.update_episode_picker()
                self.status.set("Series details loaded. Choose a season and episode.")
            else:
                self.episode_play_button.state(['disabled'])
                self.status.set("No episodes available for this series.")
        else:
            ttk.Button(info_panel, text="Play", command=self.open_player).pack(anchor="w", pady=12)
            self.status.set("Movie details loaded.")

    def update_episode_picker(self, event=None):
        episodes = self.episode_seasons.get(self.season_picker.get(), [])
        self.current_episodes = sorted(episodes, key=lambda ep: int(ep.get('episode_num') or 0) if str(ep.get('episode_num') or 0).isdigit() else 0)
        self.episode_picker.configure(values=[f"{ep.get('episode_num', index + 1)}. {ep.get('title') or 'Episode'}" for index, ep in enumerate(self.current_episodes)])
        if self.current_episodes:
            self.episode_picker.current(0)

    def play_series_episode(self):
        index = self.episode_picker.current()
        if index < 0 or index >= len(self.current_episodes):
            return
        self.selected_episode = self.current_episodes[index]
        self.open_player()

    def player_button(self, parent, text, command, primary=False):
        """Create a flat player control with consistent colors and hover feedback."""
        background = "#7c5cff" if primary else "#222b3c"
        hover = "#9278ff" if primary else "#334158"
        button = tk.Button(
            parent, text=text, command=command, background=background,
            foreground="#ffffff", activebackground=hover, activeforeground="#ffffff",
            font=("Segoe UI", 10, "bold"), relief="flat", borderwidth=0,
            padx=16, pady=10, cursor="hand2", highlightthickness=1,
            highlightbackground=background, highlightcolor="#b7a7ff",
        )
        button.bind("<Enter>", lambda event: button.configure(background=hover))
        button.bind("<Leave>", lambda event: button.configure(background=background))
        return button

    def open_player(self):
        self.clear_panel()
        # Keep the dark palette local to the player; other views retain their style.
        shell = tk.Frame(self.panel, background="#0d1320", padx=20, pady=16)
        shell.pack(fill="both", expand=True)
        toolbar = tk.Frame(shell, background="#0d1320")
        toolbar.pack(fill="x", pady=(0, 16))
        self.player_button(toolbar, "Back", self.restore_movie_details).pack(side="left")
        title_panel = tk.Frame(toolbar, background="#0d1320")
        title_panel.pack(side="left", fill="x", expand=True, padx=18)
        tk.Label(title_panel, text="NOW PLAYING", background="#0d1320", foreground="#a895ff",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        playback_title = self.selected_movie['name']
        if self.details_type == 'Series':
            playback_title += f" - {self.selected_episode.get('title') or 'Episode'}"
        tk.Label(title_panel, text=playback_title, background="#0d1320",
                 foreground="#f4f6fc", font=("Segoe UI", 15, "bold"), anchor="w",
                 wraplength=560).pack(anchor="w", pady=(3, 0))
        video_border = tk.Frame(shell, background="#293348", padx=1, pady=1)
        video_border.pack(fill="both", expand=True)
        video = tk.Frame(video_border, background="black")
        video.pack(fill="both", expand=True)
        timeline = tk.Frame(shell, background="#0d1320")
        timeline.pack(fill="x", pady=(16, 8))
        self.dragging_timeline = False
        self.playback_time = tk.StringVar(value="00:00 / --:--")
        tk.Label(timeline, textvariable=self.playback_time, background="#0d1320",
                 foreground="#d8dfee", font=("Consolas", 10)).pack(side="right", padx=(16, 0))
        self.position_slider = tk.Scale(
            timeline, from_=0, to=1, orient="horizontal", showvalue=False,
            resolution=1, highlightthickness=0, state="disabled",
            background="#0d1320", troughcolor="#293348", activebackground="#a895ff",
            foreground="#d8dfee", relief="flat", borderwidth=0,
            sliderrelief="flat", sliderlength=16, width=8, cursor="hand2",
        )
        self.position_slider.pack(side="left", fill="x", expand=True)
        self.position_slider.bind("<ButtonPress-1>", self.timeline_pressed)
        self.position_slider.bind("<B1-Motion>", self.timeline_dragged)
        self.position_slider.bind("<ButtonRelease-1>", self.timeline_released)
        self.position_slider.bind("<KeyRelease>", self.timeline_released)
        controls = tk.Frame(shell, background="#0d1320")
        controls.pack(fill="x", pady=(0, 12))
        tk.Label(shell, textvariable=self.status, background="#0d1320", foreground="#9aa8bf",
                 font=("Segoe UI", 9), anchor="w", wraplength=700).pack(anchor="w")
        self.status.set("Starting playback...")
        try:
            import vlc
            if sys.platform != 'win32':
                raise ValueError("Embedded playback currently supports Windows.")
            self.vlc_instance = vlc.Instance('--quiet', '--no-video-title-show')
            self.player = self.vlc_instance.media_player_new()
            if self.details_type == 'Series':
                extension = self.selected_episode.get('container_extension') or 'mp4'
                url = series_stream_url(*self.credentials, self.selected_episode['id'], extension)
            else:
                movie_data = self.movie_details['movie_data']
                extension = movie_data.get('container_extension') or self.selected_movie.get('container_extension') or 'mp4'
                url = movie_stream_url(*self.credentials, self.selected_movie['stream_id'], extension)
            media = self.vlc_instance.media_new(url)
            self.player.set_media(media)
            media.release()
            self.root.update_idletasks()
            self.player.set_hwnd(video.winfo_id())
            self.player.audio_set_volume(80)
            if self.player.play() == -1:
                raise ValueError("Could not start movie playback.")
            self.player_button(controls, "Play", self.player.play, primary=True).pack(side="left")
            self.player_button(controls, "Pause / Resume", self.player.pause).pack(side="left", padx=6)
            self.player_button(controls, "Stop", self.player.stop).pack(side="left")
            self.player_button(controls, "-10s", lambda: self.seek_movie(-10)).pack(side="left", padx=(16, 6))
            self.player_button(controls, "+10s", lambda: self.seek_movie(10)).pack(side="left")
            self.fullscreen_button = self.player_button(controls, "Full screen", self.toggle_fullscreen)
            self.fullscreen_button.pack(side="right")
            self.monitor_playback(self.view_id)
        except (ImportError, OSError, NameError):
            self.stop_playback()
            self.status.set("Playback requires VLC and python-vlc. Install dependencies from requirements.txt.")
        except (ValueError, AttributeError):
            self.stop_playback()
            self.status.set("Could not start playback. Check VLC installation and movie availability.")

    def seek_movie(self, seconds):
        """Seek relative to the current time, bounded by the movie's duration."""
        if self.player is None:
            return
        if not self.player.is_seekable():
            self.status.set("This movie stream does not currently support seeking.")
            return
        current = self.player.get_time()
        if current < 0:
            return
        target = max(0, current + seconds * 1000)
        duration = self.player.get_length()
        if duration > 0:
            target = min(target, max(0, duration - 1))
        self.player.set_time(int(target))

    @staticmethod
    def format_playback_time(milliseconds):
        seconds = max(0, int(milliseconds)) // 1000
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"

    def timeline_pressed(self, event=None):
        if self.player is not None and self.player.is_seekable() and self.player.get_length() > 0:
            self.dragging_timeline = True

    def timeline_dragged(self, event=None):
        if self.dragging_timeline:
            # Tk applies the drag after this handler; preview the updated position.
            view_id = self.view_id
            self.root.after_idle(lambda: self.update_timeline(view_id))

    def timeline_released(self, event=None):
        # Wait for the Scale's default mouse/key handler to update its value.
        view_id = self.view_id
        self.root.after_idle(lambda: self.seek_from_timeline(view_id))

    def seek_from_timeline(self, view_id):
        if view_id != self.view_id or self.player is None:
            return
        self.dragging_timeline = False
        duration = self.player.get_length()
        if duration > 0 and self.player.is_seekable():
            target = max(0, min(int(float(self.position_slider.get()) * 1000), duration - 1))
            self.player.set_time(target)

    def update_timeline(self, view_id):
        """Follow playback except while the user is choosing a seek position."""
        if view_id != self.view_id or self.player is None:
            return
        duration = self.player.get_length()
        current = max(0, self.player.get_time())
        can_seek = duration > 0 and self.player.is_seekable()
        self.position_slider.configure(to=max(1, duration / 1000), state="normal" if can_seek else "disabled")
        if self.dragging_timeline:
            current = int(float(self.position_slider.get()) * 1000)
        else:
            # No Scale command is registered: programmatic updates never seek.
            self.position_slider.set(current / 1000)
        total = self.format_playback_time(duration) if duration > 0 else "--:--"
        self.playback_time.set(f"{self.format_playback_time(current)} / {total}")

    def toggle_fullscreen(self, event=None):
        """Make the Tk window fullscreen so VLC remains inside its video panel."""
        if self.player is None:
            return
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)
        self.fullscreen_button.configure(text="Exit full screen" if self.fullscreen else "Full screen")

    def exit_fullscreen(self, event=None):
        if self.fullscreen:
            self.fullscreen = False
            self.root.attributes("-fullscreen", False)
            self.fullscreen_button.configure(text="Full screen")

    def monitor_playback(self, view_id):
        if view_id != self.view_id or self.player is None:
            return
        self.update_timeline(view_id)
        state = str(self.player.get_state()).split('.')[-1]
        self.status.set("Playback failed. Check connection and movie availability." if state == 'Error' else f"Playback: {state}")
        if state not in ('Error', 'Ended'):
            self.root.after(500, lambda: self.monitor_playback(view_id))

    def restore_movie_details(self):
        # Reload details on Back; leaving the player releases its native resources.
        if self.details_type == 'Series':
            self.open_series_details()
        else:
            self.open_movie_details()

    def stop_playback(self):
        # Restore windowed mode before leaving or destroying the player view.
        self.exit_fullscreen()
        if self.player is not None:
            self.player.stop()
            self.player.release()
            self.player = None
        if self.vlc_instance is not None:
            self.vlc_instance.release()
            self.vlc_instance = None

    def close(self):
        self.stop_playback()
        self.root.destroy()


def launch_ui(server="", username="", password="", timeout=20):
    """Create the window and automatically connect using the config credentials."""
    root = tk.Tk()
    StartshareUI(root, server, username, password, timeout)
    root.mainloop()
