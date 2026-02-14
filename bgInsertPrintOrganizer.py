import streamlit as st
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import urllib.parse
import pandas as pd
import xml.etree.ElementTree as ET
import time
import re

BGG_USER = "sparker0285"
TOP_N_GAMES = 10

# --- Data Classes ---
class BggGame:
    """A simple class to hold BGG game data."""
    def __init__(self, name, num_plays, last_played, objectid):
        self.name = name
        self.num_plays = num_plays
        self.last_played = last_played
        self.objectid = objectid
        self.priority_score = 0.0

class InsertResult:
    """Holds the result of a search for a 3D printable insert."""
    def __init__(self, game_name, site, url, likes=0, status="Not Found"):
        self.game_name = game_name
        self.site = site
        self.url = url
        self.likes = likes
        self.status = status

# --- 3D Print Site Scrapers ---

def find_best_insert(game_title):
    """
    Tries to find the best insert by searching sites in a specific order.
    Returns an InsertResult object.
    """
    # Site priority: MakerWorld, Thingiverse, Printables
    for site_name in ["MakerWorld", "Thingiverse", "Printables"]:
        search_url = get_search_url(site_name, game_title)
        if not search_url:
            continue

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        try:
            response = requests.get(search_url, headers=headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            if site_name == "MakerWorld":
                # MakerWorld is dynamic, we can't easily parse it. Fallback to search URL.
                return InsertResult(game_name=game_title, site=site_name, url=search_url, status="Search Page")

            elif site_name == "Thingiverse":
                best_thing = None
                max_likes = -1
                for item in soup.find_all('div', class_='search-result-item'):
                    likes_tag = item.find('span', class_='count')
                    likes = int(likes_tag.text.strip()) if likes_tag and likes_tag.text.strip().isdigit() else 0
                    
                    if likes > max_likes:
                        max_likes = likes
                        link_tag = item.find('a', class_='card-link')
                        if link_tag and link_tag.get('href'):
                            best_thing = InsertResult(
                                game_name=game_title, 
                                site=site_name, 
                                url=f"https://www.thingiverse.com{link_tag.get('href')}", 
                                likes=max_likes,
                                status="Found"
                            )
                if best_thing:
                    return best_thing

            elif site_name == "Printables":
                best_printable = None
                max_likes = -1
                for item in soup.find_all('div', class_='print-list-item'):
                    likes_tag = item.find('span', class_='label', string=re.compile(r'\d+\s+likes'))
                    likes = int(likes_tag.text.split()[0]) if likes_tag else 0

                    if likes > max_likes:
                        max_likes = likes
                        link_tag = item.find('a', class_='link')
                        if link_tag and link_tag.get('href'):
                            best_printable = InsertResult(
                                game_name=game_title,
                                site=site_name,
                                url=f"https://www.printables.com{link_tag.get('href')}",
                                likes=max_likes,
                                status="Found"
                            )
                if best_printable:
                    return best_printable
        
        except requests.RequestException:
            # If a site fails, just continue to the next one
            continue
            
    # If no sites yielded results
    return InsertResult(game_name=game_title, site="N/A", url="", status="Not Found")


def get_search_url(site, game_title):
    """Creates a search URL for the given site and game title."""
    query = f'"{game_title}" insert'
    encoded_query = urllib.parse.quote_plus(query)
    if site == "MakerWorld":
        return f"https://makerworld.com/en/search?keyword={encoded_query}"
    elif site == "Thingiverse":
        return f"https://www.thingiverse.com/search?q={encoded_query}&type=things"
    elif site == "Printables":
        return f"https://www.printables.com/search/models?q={encoded_query}"
    return None

# --- BGG API Functions ---

@st.cache_data
def get_printed_games():
    """Reads the list of printed games from the text file."""
    try:
        with open("printed_games.txt", "r") as f:
            return [line.strip() for line in f.readlines() if line.strip()]
    except FileNotFoundError:
        return []

@st.cache_data
def get_bgg_collection(username, api_key):
    """Fetches a user's collection from the BGG XML API v2."""
    collection_url = f"https://boardgamegeek.com/xmlapi2/collection?username={username}&own=1&stats=1"
    st.write("Requesting BGG collection... this can take a moment.")
    headers = {"Authorization": f"Bearer {api_key}"}
    response = requests.get(collection_url, headers=headers)
    retries = 0
    while response.status_code == 202 and retries < 10:
        st.write("...BGG is preparing your collection. Waiting and retrying...")
        time.sleep(5)
        response = requests.get(collection_url, headers=headers)
        retries += 1
    if response.status_code != 200:
        st.error(f"Failed to fetch BGG collection. Status code: {response.status_code}")
        return []
    st.write("...BGG collection received.")
    try:
        root = ET.fromstring(response.content)
        collection = [
            BggGame(
                name=item.find('name').text,
                objectid=item.get('objectid'),
                num_plays=int(item.find('numplays').text) if item.find('numplays') is not None and item.find('numplays').text is not None else 0,
                last_played=None
            )
            for item in root.findall('item') if item.find('name') is not None
        ]
        return collection
    except ET.ParseError as e:
        st.error(f"Error parsing BGG XML: {e}")
        return []

@st.cache_data
def get_bgg_plays_by_gameid(username, api_key):
    """Fetches a user's plays and returns a dictionary mapping gameid to the last played date."""
    plays_url = f"https://boardgamegeek.com/xmlapi2/plays?username={username}"
    st.write("Requesting BGG play data...")
    headers = {"Authorization": f"Bearer {api_key}"}
    response = requests.get(plays_url, headers=headers)
    if response.status_code != 200:
        st.error(f"Failed to fetch BGG plays. Status code: {response.status_code}")
        return {}
    st.write("...BGG play data received.")
    plays_by_gameid = {}
    try:
        root = ET.fromstring(response.content)
        for play in root.findall('play'):
            play_date_str = play.get('date')
            game_item = play.find('item')
            if game_item is not None:
                gameid = game_item.get('objectid')
                if play_date_str and gameid:
                    play_date = datetime.strptime(play_date_str, '%Y-%m-%d')
                    if gameid not in plays_by_gameid or play_date > plays_by_gameid[gameid]:
                        plays_by_gameid[gameid] = play_date
        return plays_by_gameid
    except ET.ParseError as e:
        st.error(f"Error parsing BGG plays XML: {e}")
        return {}

# --- Main Application Logic ---

def main():
    st.set_page_config(layout="wide")
    st.title("Insert Curator")
    st.write(f"Cross-referencing **{BGG_USER}**'s BGG collection with 3D print repositories.")

    bgg_api_key = st.secrets.get("bgg_api_key")

    if not bgg_api_key or bgg_api_key == "YOUR_BGG_API_KEY_HERE":
        st.info("Please add your BGG API Key to your .streamlit/secrets.toml file to begin.")
        return

    search_query = st.text_input("Search all games in your collection:", "")

    collection = get_bgg_collection(BGG_USER, bgg_api_key)
    if not collection:
        return

    # --- Game Prioritization Logic ---
    plays_by_gameid = get_bgg_plays_by_gameid(BGG_USER, bgg_api_key)
    for game in collection:
        if game.objectid in plays_by_gameid:
            game.last_played = plays_by_gameid[game.objectid]

    # Filter collection based on search query
    if search_query:
        collection = [game for game in collection if search_query.lower() in game.name.lower()]

    printed_games_list = get_printed_games()
    
    # Separate printed games from the main collection
    unprinted_games = [g for g in collection if g.name not in printed_games_list]
    printed_games = [g for g in collection if g.name in printed_games_list]

    # Prioritize unprinted games that have been played
    eligible_games = [g for g in unprinted_games if g.last_played]

    if not eligible_games:
        st.warning("No played games found in your collection that aren't on the 'printed' list.")
    else:
        # Calculate Priority Score for eligible games
        max_plays = max(g.num_plays for g in eligible_games) if eligible_games else 1
        today = datetime.now()
        max_recency_days = max(((today - g.last_played).days for g in eligible_games), default=1)

        for game in eligible_games:
            norm_plays = game.num_plays / max_plays if max_plays > 0 else 0
            days_since_played = (today - game.last_played).days
            norm_recency = 1.0 - (days_since_played / max_recency_days) if max_recency_days > 0 else 0
            weight_plays = 0.6
            weight_recency = 0.4
            game.priority_score = (weight_plays * norm_plays) + (weight_recency * norm_recency)

        # Sort games by the new priority score
        priority_games = sorted(eligible_games, key=lambda x: x.priority_score, reverse=True)[:TOP_N_GAMES]

        st.subheader(f"Top {TOP_N_GAMES} Games to Find Inserts For")
        
        if not priority_games:
            st.write("Could not determine any priority games.")
        else:
            # --- Search and Display Results for Priority Games ---
            search_results_data = []
            progress_bar = st.progress(0)
            status_text = st.empty()

            for i, game in enumerate(priority_games):
                status_text.text(f"Searching for: {game.name}...")
                insert_result = find_best_insert(game.name)
                search_results_data.append({
                    "Game Title": game.name,
                    "Priority": f"{game.priority_score:.2f}",
                    "Plays": game.num_plays,
                    "Last Played": game.last_played.strftime('%Y-%m-%d') if game.last_played else "N/A",
                    "Found on": insert_result.site,
                    "Likes": insert_result.likes if insert_result.status == "Found" else "N/A",
                    "Insert URL": insert_result.url,
                })
                progress_bar.progress((i + 1) / len(priority_games))
            
            status_text.text("Search complete!")
            
            if search_results_data:
                df = pd.DataFrame(search_results_data)
                st.dataframe(df)

    # --- Display Printed Games ---
    if printed_games:
        st.subheader("Printed Games")
        for game in sorted(printed_games, key=lambda x: x.name):
            with st.expander(f"{game.name}"):
                st.write("**Status: PRINTED**")
                st.write(f"Plays: {game.num_plays}")
                st.write(f"Last Played: {game.last_played.strftime('%Y-%m-%d') if game.last_played else 'N/A'}")


if __name__ == "__main__":
    main()
