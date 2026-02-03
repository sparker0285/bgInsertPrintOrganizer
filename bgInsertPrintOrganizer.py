import streamlit as st
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import urllib.parse
import pandas as pd
import xml.etree.ElementTree as ET
import time

BGG_USER = "sparker0285"
DAYS_SINCE_LAST_PLAY = 365

class BggGame:
    """A simple class to hold BGG game data."""
    def __init__(self, name, num_plays, last_played):
        self.name = name
        self.num_plays = num_plays
        self.last_played = last_played

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

def search_site(game_title, site):
    """Searches a given site for a game title and returns the result count and URL."""
    search_url = get_search_url(site, game_title)
    if not search_url:
        return "Unsupported site", 0

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        response = requests.get(search_url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        count = 0
        if site == "MakerWorld": # Placeholder - MW uses dynamic loading
            results = soup.find_all('div', class_='card-item')
            count = len(results) if results else 0
        elif site == "Thingiverse":
            results = soup.find_all('div', class_='search-result-item') # Updated selector
            count = len(results) if results else 0
        elif site == "Printables":
            results = soup.find_all('div', class_='print-list-item') # Updated selector
            count = len(results) if results else 0
        
        return search_url, count
    except requests.RequestException as e:
        return f"Error: {e}", 0

@st.cache_data
def get_printed_games():
    """Reads the list of printed games from the text file."""
    try:
        with open("printed_games.txt", "r") as f:
            return [line.strip() for line in f.readlines() if line.strip()]
    except FileNotFoundError:
        return []

@st.cache_data
def get_bgg_collection(username):
    """Fetches a user's collection from the BGG XML API v2."""
    collection_url = f"https://boardgamegeek.com/xmlapi2/collection?username={username}&own=1&stats=1"
    
    st.write("Requesting BGG collection... this can take a moment.")
    
    # BGG API v2 can return a 202 status, meaning the request is queued.
    # We need to poll until we get a 200.
    response = requests.get(collection_url)
    retries = 0
    while response.status_code == 202 and retries < 10:
        st.write("...BGG is preparing your collection. Waiting and retrying...")
        time.sleep(5) # Wait 5 seconds before retrying
        response = requests.get(collection_url)
        retries += 1

    if response.status_code != 200:
        st.error(f"Failed to fetch BGG collection. Status code: {response.status_code}")
        st.write(response.text)
        return []

    st.write("...BGG collection received. Parsing XML.")
    
    try:
        root = ET.fromstring(response.content)
        collection = []
        for item in root.findall('item'):
            name = item.find('name').text
            num_plays = int(item.find('numplays').text)
            last_played_str = item.find('lastmodified').text # Using lastmodified as a proxy if lastplayed is absent
            
            stats = item.find('stats')
            if stats is not None:
                last_played_tag = stats.find('lastplayed')
                if last_played_tag is not None and last_played_tag.text:
                     last_played_str = last_played_tag.text

            last_played = None
            if last_played_str:
                try:
                    # BGG date format can be 'YYYY-MM-DD HH:MM:SS' or just 'YYYY-MM-DD'
                    last_played = datetime.strptime(last_played_str.split(' ')[0], '%Y-%m-%d')
                except (ValueError, TypeError):
                    last_played = None # Ignore if date is invalid
            
            collection.append(BggGame(name=name, num_plays=num_plays, last_played=last_played))
        
        st.write(f"Successfully parsed {len(collection)} games from your collection.")
        return collection
    except ET.ParseError as e:
        st.error(f"Error parsing BGG XML response: {e}")
        return []


def main():
    st.set_page_config(layout="wide")
    st.title("Insert Curator")
    st.write(f"Cross-referencing **{BGG_USER}**'s BGG collection with 3D print repositories.")

    printed_games = get_printed_games()
    st.sidebar.subheader("Already Printed")
    st.sidebar.expander("Expand").write(printed_games if printed_games else "None yet.")

    collection = get_bgg_collection(BGG_USER)
    
    if collection:
        today = datetime.now()
        cutoff_date = today - timedelta(days=DAYS_SINCE_LAST_PLAY)
        
        priority_games = []
        for game in collection:
            if game.last_played and game.last_played > cutoff_date and game.name not in printed_games:
                priority_games.append(game)

        if not priority_games and collection:
            st.warning(f"No games played in the last {DAYS_SINCE_LAST_PLAY} days. Falling back to the 10 most played games not on the printed list.")
            all_owned_games = sorted(
                [g for g in collection if g.name not in printed_games],
                key=lambda x: x.num_plays,
                reverse=True
            )
            priority_games = all_owned_games[:10]

        st.subheader("Top Games to Find Inserts For")
        
        if priority_games:
            search_results_data = []
            
            progress_bar = st.progress(0)
            status_text = st.empty()

            for i, game in enumerate(priority_games):
                status_text.text(f"Searching for: {game.name}...")
                
                search_url, count = search_site(game.name, "MakerWorld")
                if count == 0:
                    search_url, count = search_site(game.name, "Thingiverse")
                if count == 0:
                    search_url, count = search_site(game.name, "Printables")

                search_results_data.append({
                    "Game Title": game.name,
                    "Plays": game.num_plays,
                    "Search URL": search_url,
                    "Result Count": count,
                })
                progress_bar.progress((i + 1) / len(priority_games))
            
            status_text.text("Search complete!")
            
            if search_results_data:
                df = pd.DataFrame(search_results_data)
                st.dataframe(df)

        else:
            st.write("No priority games found to search for.")

if __name__ == "__main__":
    main()

