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
import re

BGG_USER = "sparker0285"
DAYS_SINCE_LAST_PLAY = 365
AZURE_CONTAINER_NAME = "bgg-data"
AZURE_COLLECTION_BLOB = "collection.json"
AZURE_PRINTED_BLOB = "printed_games.json"
AZURE_SEARCH_RESULTS_BLOB = "search_results_v2.json"

class BggGame:
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

# --- Azure Helpers ---
def get_azure_blob_service():
    try:
        connect_str = st.secrets["azure_storage_connection_string"]
        return BlobServiceClient.from_connection_string(connect_str)
    except Exception as e:
        st.error(f"Failed to connect to Azure Storage: {e}")
        return None

def save_json_to_azure(data, blob_name):
    blob_service_client = get_azure_blob_service()
    if not blob_service_client: return
    try:
        container_client = blob_service_client.get_container_client(AZURE_CONTAINER_NAME)
        if not container_client.exists(): container_client.create_container()
        blob_client = container_client.get_blob_client(blob_name)
        blob_client.upload_blob(json.dumps(data), overwrite=True)
    except Exception as e: st.error(f"Failed to save {blob_name}: {e}")

def load_json_from_azure(blob_name):
    blob_service_client = get_azure_blob_service()
    if not blob_service_client: return None
    try:
        blob_client = blob_service_client.get_blob_client(container=AZURE_CONTAINER_NAME, blob=blob_name)
        if not blob_client.exists(): return None
        return json.loads(blob_client.download_blob().readall())
    except Exception: return None

def get_printed_games():
    printed_games = load_json_from_azure(AZURE_PRINTED_BLOB)
    if printed_games is None:
        try:
            with open("printed_games.txt", "r") as f:
                printed_games = [line.strip() for line in f.readlines() if line.strip()]
            save_json_to_azure(printed_games, AZURE_PRINTED_BLOB)
        except FileNotFoundError:
            printed_games = []
    return printed_games

# --- BGG Logic ---
def get_auth_headers():
    headers = {"User-Agent": "InsertCurator/1.0", "Accept": "application/xml"}
    try:
        if st.secrets["bgg_api_key"]: headers["Authorization"] = f"Bearer {st.secrets['bgg_api_key']}"
    except: pass
    return headers

def fetch_play_history(username):
    session = requests.Session()
    session.headers.update(get_auth_headers())
    play_dates = {}
    page = 1
    max_pages = 5
    st.write("Fetching recent play history...")
    progress_text = st.empty()
    while page <= max_pages:
        progress_text.text(f"Fetching plays page {page}...")
        try:
            r = session.get(f"https://boardgamegeek.com/xmlapi2/plays?username={username}&page={page}")
            if r.status_code != 200: break
            root = ET.fromstring(r.content)
            plays = root.findall('play')
            if not plays: break
            for play in plays:
                date_str = play.get('date')
                item = play.find('item')
                if item is not None:
                    game_id = item.get('objectid')
                    try:
                        play_date = datetime.strptime(date_str, '%Y-%m-%d')
                        if game_id not in play_dates or play_date > play_dates[game_id]:
                            play_dates[game_id] = play_date
                    except: continue
            page += 1
            time.sleep(1)
        except: break
    progress_text.empty()
    return play_dates

def fetch_bgg_collection_from_api(username):
    session = requests.Session()
    session.headers.update(get_auth_headers())
    st.write("Requesting BGG collection...")
    resp = session.get(f"https://boardgamegeek.com/xmlapi2/collection?username={username}&own=1&stats=1")
    while resp.status_code == 202: time.sleep(5); resp = session.get(resp.url)
    if resp.status_code != 200: return []
    
    play_dates = fetch_play_history(username)
    try:
        root = ET.fromstring(resp.content)
        collection = []
        for item in root.findall('item'):
            gid = item.get('objectid')
            name = item.find('name').text if item.find('name') is not None else "Unknown"
            plays = int(item.find('numplays').text) if item.find('numplays') is not None else 0
            last_played = play_dates.get(gid)
            if not last_played:
                try:
                    lp_tag = item.find('stats').find('lastplayed')
                    if lp_tag is not None and lp_tag.text:
                        last_played = datetime.strptime(lp_tag.text.split(' ')[0], '%Y-%m-%d')
                except: pass
            collection.append(BggGame(gid, name, plays, last_played))
        return collection
    except: return []

# --- Scraper & AI Logic ---
def scrape_thingiverse_details(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200: return None
        soup = BeautifulSoup(resp.content, 'html.parser')
        desc_div = soup.find('div', class_=re.compile(r'description', re.I))
        if desc_div: return desc_div.get_text(strip=True)[:2000]
        return ""
    except: return None

def scrape_printables_details(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200: return None
        soup = BeautifulSoup(resp.content, 'html.parser')
        desc_div = soup.find('div', {'id': 'description'})
        if not desc_div: desc_div = soup.find('div', class_=re.compile(r'description', re.I))
        if desc_div: return desc_div.get_text(strip=True)[:2000]
        return ""
    except: return None

@st.cache_data(ttl=3600)
def get_valid_gemini_model(api_key):
    """Dynamically fetches available models and picks the best one."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        response = requests.get(url)
        if response.status_code != 200:
            return None, f"Error listing models: {response.status_code}"
        
        data = response.json()
        models = data.get('models', [])
        
        # Priority list
        priorities = ["gemini-1.5-flash", "gemini-flash", "gemini-1.5-pro", "gemini-pro"]
        
        # 1. Try to find exact matches or partial matches from priority list
        for p in priorities:
            for m in models:
                if p in m['name']:
                    return m['name'], None
        
        # 2. Fallback: any gemini model
        for m in models:
            if "gemini" in m['name'] and "vision" not in m['name']: # Avoid vision-only if any
                return m['name'], None
                
        return None, "No suitable Gemini model found."
    except Exception as e:
        return None, f"Exception listing models: {e}"

def evaluate_insert_with_ai(game_name, search_url, site):
    api_key = st.secrets.get("google_api_key")
    if not api_key: return 0, "Missing API Key"

    # Get a valid model name dynamically
    model_name, error_msg = get_valid_gemini_model(api_key)
    if not model_name:
        return 5, f"AI Setup Error: {error_msg}"

    details_text = ""
    if site == "Thingiverse" and "thingiverse.com/thing:" in search_url:
        details_text = scrape_thingiverse_details(search_url)
    elif site == "Printables" and "printables.com/model" in search_url:
        details_text = scrape_printables_details(search_url)
    
    context = f"Game: {game_name}. Site: {site}. URL: {search_url}. "
    if details_text: context += f"Description Snippet: {details_text}"
    else: context += "I cannot scrape the full page content directly."

    prompt = (
        f"{context}\n\n"
        "Evaluate the likely quality and utility of a 3D printed insert for this board game. "
        "Consider factors like: does this game need an insert? Are there known good designs? "
        "If you have description text above, analyze it for keywords like 'sleeved cards', 'vertical storage', 'lid lift'. "
        "Provide a JSON response with:\n"
        "- score: (integer 1-10, where 10 is essential/perfect design)\n"
        "- summary: (short 1-sentence summary of why)\n"
        "If you have absolutely no info, guess a conservative 5."
    )

    # Construct URL using the dynamically found model name
    # model_name usually comes as "models/gemini-pro", so we use it directly in the path
    url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    data = {"contents": [{"parts": [{"text": prompt}]}]}

    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code != 200:
            return 5, f"AI API Error ({model_name}): {response.status_code}"
        
        result = response.json()
        try:
            text = result['candidates'][0]['content']['parts'][0]['text']
            if "```json" in text: text = text.split("```json")[1].split("```")[0]
            elif "```" in text: text = text.split("```")[1].split("```")[0]
            data = json.loads(text)
            return data.get("score", 5), data.get("summary", "No summary.")
        except (KeyError, IndexError, json.JSONDecodeError):
             return 5, "AI Response Parse Error"
             
    except Exception as e:
        return 5, f"AI Error: {str(e)[:50]}"

def find_best_candidate(game_name):
    search_term = urllib.parse.quote_plus(f"{game_name} insert")
    tv_url = f"https://www.thingiverse.com/search?q={search_term}&type=things&sort=popular"
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(tv_url, headers=headers)
        soup = BeautifulSoup(r.content, 'html.parser')
        item = soup.find('a', class_=re.compile(r'card-img-holder|search-result', re.I))
        if item and item.get('href'):
            full_link = item.get('href')
            if not full_link.startswith('http'): full_link = "https://www.thingiverse.com" + full_link
            return full_link, "Thingiverse"
    except: pass
    return f"https://makerworld.com/en/search?keyword={search_term}", "MakerWorld"

def process_ai_evaluations(results_list, limit=20):
    count = 0
    updated = False
    
    if st.session_state.get("batch_run_complete", False):
        return results_list, False

    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, item in enumerate(results_list):
        if count >= limit: break
        
        needs_eval = not item.get("AI_Evaluated", False)
        if not needs_eval and "AI Config Error" in str(item.get("AI_Summary", "")): needs_eval = True
        if not needs_eval and "AI Error" in str(item.get("AI_Summary", "")): needs_eval = True
        if not needs_eval and "AI API Error" in str(item.get("AI_Summary", "")): needs_eval = True
        if not needs_eval and "AI Setup Error" in str(item.get("AI_Summary", "")): needs_eval = True

        if needs_eval:
            status_text.text(f"Evaluating {item['Game Title']} with AI...")
            candidate_url, site = find_best_candidate(item['Game Title'])
            score, summary = evaluate_insert_with_ai(item['Game Title'], candidate_url, site)
            
            item["AI_Score"] = score
            item["AI_Summary"] = summary
            item["AI_Evaluated"] = True
            item["Candidate_URL"] = candidate_url
            item["Priority_Score"] = item["Plays"] + item["AI_Score"]
            
            updated = True
            count += 1
            progress_bar.progress(count / limit)
            time.sleep(1) 
            
    st.session_state.batch_run_complete = True
    progress_bar.empty()
    status_text.empty()
    return results_list, updated

# --- Main App ---
def main():
    st.set_page_config(layout="wide")
    st.title("Insert Curator")
    
    # Load Data
    printed_games = get_printed_games() or []
    collection_data = load_json_from_azure(AZURE_COLLECTION_BLOB)
    search_results = load_json_from_azure(AZURE_SEARCH_RESULTS_BLOB) or []

    # Sidebar
    if st.sidebar.button("Refresh Collection from BGG"):
        st.session_state.batch_run_complete = False 
        collection = fetch_bgg_collection_from_api(BGG_USER)
        if collection:
            save_json_to_azure([g.to_dict() for g in collection], AZURE_COLLECTION_BLOB)
            st.rerun()
            
    if st.sidebar.button("Show Printed Games List"):
        st.session_state.show_printed_list = not st.session_state.get("show_printed_list", False)

    if st.session_state.get("show_printed_list"):
        st.sidebar.markdown("### Already Printed")
        st.sidebar.dataframe(printed_games, hide_index=True, use_container_width=True)

    # Initial Load / Sync
    if not collection_data:
        st.info("Fetching collection for the first time...")
        collection = fetch_bgg_collection_from_api(BGG_USER)
        if collection:
            save_json_to_azure([g.to_dict() for g in collection], AZURE_COLLECTION_BLOB)
            collection_data = [g.to_dict() for g in collection]
            st.rerun()
    
    # Process Collection -> Priority List
    if collection_data:
        games = [BggGame.from_dict(d) for d in collection_data]
        cutoff = datetime.now() - timedelta(days=DAYS_SINCE_LAST_PLAY)
        priority_games = [g for g in games if g.last_played and g.last_played > cutoff and g.name not in printed_games]
        
        if not priority_games:
            priority_games = sorted([g for g in games if g.name not in printed_games], key=lambda x: x.num_plays, reverse=True)[:50]
        
        cached_map = {item["Game Title"]: item for item in search_results}
        final_list = []
        
        for game in priority_games:
            if game.name in cached_map:
                existing = cached_map[game.name]
                existing["Plays"] = game.num_plays
                existing["Last Played"] = game.last_played.strftime('%Y-%m-%d') if game.last_played else "N/A"
                if existing.get("AI_Score"):
                    existing["Priority_Score"] = existing["Plays"] + existing["AI_Score"]
                else:
                    existing["Priority_Score"] = existing["Plays"]
                final_list.append(existing)
            else:
                final_list.append({
                    "Game Title": game.name,
                    "Plays": game.num_plays,
                    "Last Played": game.last_played.strftime('%Y-%m-%d') if game.last_played else "N/A",
                    "AI_Evaluated": False,
                    "AI_Score": 0,
                    "AI_Summary": "Pending...",
                    "Priority_Score": game.num_plays,
                    "Search URL": f"https://makerworld.com/en/search?keyword={urllib.parse.quote_plus(game.name + ' insert')}"
                })
        
        final_list.sort(key=lambda x: x["Priority_Score"], reverse=True)
        
        # Batch AI Evaluation
        final_list, updated = process_ai_evaluations(final_list, limit=20)
        if updated:
            save_json_to_azure(final_list, AZURE_SEARCH_RESULTS_BLOB)

        st.subheader("Top Games to Find Inserts For")
        
        for i, item in enumerate(final_list):
            # Expander Header
            header_text = f"**{item['Game Title']}** | Plays: {item['Plays']} | Priority: {item['Priority_Score']}"
            
            with st.expander(header_text, expanded=False):
                c1, c2, c3 = st.columns([2, 3, 1])
                
                with c1:
                    st.markdown("### Model Link")
                    url = item.get('Candidate_URL', item['Search URL'])
                    st.markdown(f"🔗 [Open Model Page]({url})")
                    st.caption(f"Source: {url}")

                with c2:
                    st.markdown("### AI Analysis")
                    st.metric("Quality Score", f"{item['AI_Score']}/10")
                    st.info(item['AI_Summary'])

                with c3:
                    st.markdown("### Actions")
                    if st.button("✅ Printed", key=f"print_{i}", help="Mark as Printed"):
                        printed_games.append(item['Game Title'])
                        save_json_to_azure(printed_games, AZURE_PRINTED_BLOB)
                        new_results = [r for r in final_list if r['Game Title'] != item['Game Title']]
                        save_json_to_azure(new_results, AZURE_SEARCH_RESULTS_BLOB)
                        st.rerun()
                    
                    if st.button("🔄 Re-Eval AI", key=f"reeval_{i}"):
                        with st.spinner("Re-evaluating..."):
                            candidate_url, site = find_best_candidate(item['Game Title'])
                            score, summary = evaluate_insert_with_ai(item['Game Title'], candidate_url, site)
                            item["AI_Score"] = score
                            item["AI_Summary"] = summary
                            item["AI_Evaluated"] = True
                            item["Candidate_URL"] = candidate_url
                            item["Priority_Score"] = item["Plays"] + item["AI_Score"]
                            save_json_to_azure(final_list, AZURE_SEARCH_RESULTS_BLOB)
                        st.rerun()

if __name__ == "__main__":
    main()
