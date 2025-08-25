
import pandas as pd
from flask import Flask, render_template, request, jsonify, redirect, session, url_for
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv, find_dotenv
import os
import requests

# --- Load .env (force override to avoid stale env vars) ---
load_dotenv(override=True)


# --- Spotify credentials ---
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI") or "http://127.0.0.1:5000/callback"  # must match Spotify dashboard
# --- Credential sanity check ---
resp = requests.post(
    "https://accounts.spotify.com/api/token",
    data={"grant_type": "client_credentials"},
    auth=(CLIENT_ID, CLIENT_SECRET),
)
print("Spotify auth test status:", resp.status_code)
print("Spotify auth test response:", resp.json())
if resp.status_code != 200:
    raise ValueError("❌ Spotify credentials invalid. Check CLIENT_ID / CLIENT_SECRET in your .env")

# Flask app
app = Flask(__name__)
app.secret_key = "supersecretkey"  # ⚠️ change in production!

# Spotify OAuth setup
scope = "user-library-read playlist-modify-public playlist-modify-private user-read-email user-read-private"

sp_oauth = SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=scope,
    cache_handler=None  # disable cache to avoid stale data
)
print("CLIENT_SECRET length:", len(CLIENT_SECRET or "None"))
print("CLIENT_SECRET raw:", repr(CLIENT_SECRET))


# --- Load dataset ---
df = pd.read_csv("spotify_tracks.csv").fillna("")

# Mood mapping
def get_mood(val):
    if val < 0.3:
        return "Sad"
    elif val < 0.6:
        return "Calm"
    else:
        return "Happy"

df["mood"] = df["valence"].apply(get_mood)

# Language mapping
def map_language(genre):
    genre = str(genre).lower()
    if "k-pop" in genre:
        return "Korean"
    elif "j-pop" in genre or "anime" in genre:
        return "Japanese"
    elif "latin" in genre or "reggaeton" in genre or "brazil" in genre or "forro" in genre:
        return "Spanish/Portuguese"
    elif "indian" in genre or "bollywood" in genre or "hindi" in genre or "desi" in genre:
        return "Hindi"
    elif "french" in genre or "chanson" in genre:
        return "French"
    elif "german" in genre:
        return "German"
    elif "cantopop" in genre or "mandopop" in genre:
        return "Chinese"
    else:
        return "English"

df["language"] = df["track_genre"].apply(map_language)

# ---------- ROUTES ----------
@app.route("/")
def index():
    moods = sorted(df["mood"].unique().tolist())
    genres = sorted(df["track_genre"].unique().tolist())
    languages = sorted(df["language"].unique().tolist())

    user_name = None
    if "token_info" in session:
        sp = get_spotify_client()
        if sp:
            user = sp.current_user()
            user_name = user.get("display_name", user.get("id"))

    return render_template("index.html", moods=moods, genres=genres, languages=languages, user_name=user_name)

@app.route("/login")
def login():
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

@app.route("/callback")
def callback():
    code = request.args.get("code")
    token_info = sp_oauth.get_access_token(code, as_dict=True)
    session["token_info"] = token_info
    return redirect(url_for("index"))

@app.route("/logout")
def logout():
    session.pop("token_info", None)
    return redirect(url_for("index"))

def get_spotify_client():
    token_info = session.get("token_info", None)
    if not token_info:
        return None
    if sp_oauth.is_token_expired(token_info):
        token_info = sp_oauth.refresh_access_token(token_info["refresh_token"])
        session["token_info"] = token_info
    return spotipy.Spotify(auth=token_info["access_token"])

@app.route("/generate", methods=["POST"])
def generate_playlist():
    mood = request.form.get("mood")
    genre = request.form.get("genre")
    language = request.form.get("language")
    num_songs = int(request.form.get("num_songs", 20))

    playlist = df.copy()
    if mood and mood != "Any":
        playlist = playlist[playlist["mood"] == mood]
    if genre and genre != "Any":
        playlist = playlist[playlist["track_genre"] == genre]
    if language and language != "Any":
        playlist = playlist[playlist["language"] == language]

    if not playlist.empty:
        playlist = playlist.sample(min(num_songs, len(playlist)))
    else:
        playlist = pd.DataFrame()

    return jsonify(playlist.to_dict(orient="records"))

@app.route("/save_playlist", methods=["POST"])
def save_playlist():
    sp = get_spotify_client()
    if not sp:
        return jsonify({"error": "Not logged in"}), 401

    user_id = sp.current_user()["id"]
    data = request.get_json()
    playlist_name = data.get("name", "My Generated Playlist")
    tracks = data.get("tracks", [])

    new_playlist = sp.user_playlist_create(user=user_id, name=playlist_name, public=False)
    playlist_id = new_playlist["id"]

    track_uris = [f"spotify:track:{t}" for t in tracks]
    if track_uris:
        sp.playlist_add_items(playlist_id, track_uris)

    return jsonify({"success": True, "playlist_url": new_playlist["external_urls"]["spotify"]})

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
