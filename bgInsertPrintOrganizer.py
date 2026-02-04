import streamlit as st
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import urllib.parse
import pandas as pd
import xml.etree.ElementTree as ET
import time
import json
from azure.storage.blob import BlobServiceClient

BGG_USER = "sparker0285"
DAYS_SINCE_LAST_PLAY = 365
AZURE_CONTAINER_NAME = "bgg-data"
AZURE_BLOB_NAME = "collection.json"

class BggGame:
    """A simple class to hold BGG game data."""
    def __init__(self, game_id, name, num_plays, last_played):
        self.game_id = game_id
        self.name = name
        self.num_plays = num_plays
        self.last_played = last_played
    
    def to_dict(self):
        return {
            "game_id": self.game_id,
            "name": self.name,
            "num_plays": self.num_plays,
            "last_played": self.last_played.isoformat() if self.last_played else None
        }

    @classmethod
    def from_dict(cls, data):
        last_played = datetime.fromisoformat(data["last_played"]) if data.get("last_played") else None
        return cls(data.get("game_id"), data["name"], data["num_plays"], last_played)

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

def get_azure_blob_service():
    """Creates a BlobServiceClient using the connection string from secrets."""
    try:
        connect_str = st.secrets["azure_storage_connection_string"]
        return BlobServiceClient.from_connection_string(connect_str)
    except Exception as e:
        st.error(f"Failed to connect to Azure Storage: {e}")
        return None

def save_collection_to_azure(collection):
    """Saves the collection to Azure Blob Storage as JSON."""
    blob_service_client = get_azure_blob_service()
    if not blob_service_client:
        return

    try:
        container_client = blob_service_client.get_container_client(AZURE_CONTAINER_NAME)
        if not container_client.exists():
            container_client.create_container()

        blob_client = container_client.get_blob_client(AZURE_BLOB_NAME)
        
        data = [game.to_dict() for game in collection]
        json_data = json.dumps(data)
        
        blob_client.upload_blob(json_data, overwrite=True)
        st.success("Collection saved to Azure Storage.")
    except Exception as e:
        st.error(f"Failed to save to Azure Storage: {e}")

def load_collection_from_azure():
    """Loads the collection from Azure Blob Storage."""
    blob_service_client = get_azure_blob_service()
    if not blob_service_client:
        return None

    try:
        blob_client = blob_service_client.get_blob_client(container=AZURE_CONTAINER_NAME, blob=AZURE_BLOB_NAME)
        
        if not blob_client.exists():
            return None
            
        download_stream = blob_client.download_blob()
        json_data = download_stream.readall()
        data = json.loads(json_data)
        
        return [BggGame.from_dict(item) for item in data]
    except Exception as e:
        st.warning(f"Could not load from Azure Storage: {e}")
        return None

def get_auth_headers():
    """Constructs headers with Bearer token if available."""
    headers = {
        "User-Agent": "InsertCurator/1.0 (Streamlit App)",
        "Accept": "application/xml"
    }
    try:
        api_key = st.secrets["bgg_api_key"]
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
    except Exception:
        pass
    return headers

def fetch_play_history(username):
    """Fetches play history to get accurate last played dates."""
    session = requests.Session()
    session.headers.update(get_auth_headers())
    
    play_dates = {} # game_id -> last_played_date (datetime)
    
    page = 1
    max_pages = 5 # Limit to recent history to avoid long load times
    
    st.write("Fetching recent play history...")
    progress_text = st.empty()
    
    while page <= max_pages:
        progress_text.text(f"Fetching plays page {page}...")
        url = f"https://boardgamegeek.com/xmlapi2/plays?username={username}&page={page}"
        
        try:
            r = session.get(url)
            if r.status_code != 200:
                st.warning(f"Failed to fetch plays page {page}: {r.status_code}")
                break
            
            root = ET.fromstring(r.content)
            plays = root.findall('play')
            
            if not plays:
                break # No more plays
            
            for play in plays:
                date_str = play.get('date')
                item = play.find('item')
                if item is not None:
                    game_id = item.get('objectid')
                    try:
                        play_date = datetime.strptime(date_str, '%Y-%m-%d')
                        # We only care about the most recent date for each game
                        if game_id not in play_dates or play_date > play_dates[game_id]:
                            play_dates[game_id] = play_date
                    except (ValueError, TypeError):
                        continue
            
            page += 1
            time.sleep(1) # Be polite to API
            
        except Exception as e:
            st.error(f"Error fetching plays: {e}")
            break
            
    progress_text.empty()
    st.write(f"Found play history for {len(play_dates)} games.")
    return play_dates

def fetch_bgg_collection_from_api(username):
    """Fetches a user's collection and merges with play history."""
    
    # 1. Fetch Collection
    collection_url = f"https://boardgamegeek.com/xmlapi2/collection?username={username}&own=1&stats=1"
    st.write("Requesting BGG collection from API...")
    
    session = requests.Session()
    session.headers.update(get_auth_headers())
    
    response = session.get(collection_url)
    retries = 0
    while response.status_code == 202 and retries < 10:
        st.write("...BGG is preparing your collection. Waiting...")
        time.sleep(5)
        response = session.get(collection_url)
        retries += 1

    if response.status_code != 200:
        st.error(f"Failed to fetch BGG collection. Status code: {response.status_code}")
        return []

    # 2. Fetch Play History
    play_dates = fetch_play_history(username)

    st.write("...Parsing collection and merging play data.")
    
    try:
        root = ET.fromstring(response.content)
        collection = []
        for item in root.findall('item'):
            game_id = item.get('objectid')
            name_tag = item.find('name')
            name = name_tag.text if name_tag is not None else "Unknown Game"
            
            num_plays_tag = item.find('numplays')
            num_plays = int(num_plays_tag.text) if num_plays_tag is not None else 0
            
            # Default to None, then check play history
            last_played = play_dates.get(game_id)
            
            # Fallback to collection data if not in recent plays
            if not last_played:
                last_modified_tag = item.find('lastmodified')
                if last_modified_tag is not None:
                    try:
                        # lastmodified is not lastplayed, but it's a fallback
                        # actually, let's check stats.lastplayed first
                        stats = item.find('stats')
                        if stats is not None:
                            lp_tag = stats.find('lastplayed')
                            if lp_tag is not None and lp_tag.text:
                                last_played = datetime.strptime(lp_tag.text.split(' ')[0], '%Y-%m-%d')
                    except:
                        pass

            collection.append(BggGame(game_id=game_id, name=name, num_plays=num_plays, last_played=last_played))
        
        st.write(f"Successfully parsed {len(collection)} games.")
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

    # Azure Storage Logic
    collection = None
    
    # Check if we should force refresh
    force_refresh = st.sidebar.button("Refresh Collection from BGG")
    
    if not force_refresh:
        st.sidebar.write("Checking Azure Storage for cached collection...")
        collection = load_collection_from_azure()
        if collection:
            st.sidebar.success(f"Loaded {len(collection)} games from Azure Storage.")
        else:
            st.sidebar.warning("No collection found in Azure Storage.")

    if not collection or force_refresh:
        collection = fetch_bgg_collection_from_api(BGG_USER)
        if collection:
            save_collection_to_azure(collection)

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
                    "Last Played": game.last_played.strftime('%Y-%m-%d') if game.last_played else "N/A",
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

