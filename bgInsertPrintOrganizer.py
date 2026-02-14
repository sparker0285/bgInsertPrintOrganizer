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
AZURE_EXCLUDED_BLOB = "excluded_games.json"
AZURE_SEARCH_RESULTS_BLOB = "search_results_v2.json"
AZURE_ERROR_LOG_BLOB = "error_log.json"

MODELS_TO_TRY = [
    "gemini-2.5-flash-lite", # Default
    "gemini-1.5-flash",
    "gemini-1.5-flash8b",
    "gemini-2.5-flash"
]

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

def get_list_from_azure(blob_name, fallback_file=None):
    data = load_json_from_azure(blob_name)
    if data is None and fallback_file:
        try:
            with open(fallback_file, "r") as f:
                data = [line.strip() for line in f.readlines() if line.strip()]
            save_json_to_azure(data, blob_name)
        except FileNotFoundError:
            data = []
    return data or []

def log_error_to_azure(game_name, model_name, status_code, response_text):
    logs = load_json_from_azure(AZURE_ERROR_LOG_BLOB) or []
    new_log = {
        "timestamp": datetime.now().isoformat(),
        "game": game_name,
        "model": model_name,
        "status": status_code,
        "response": response_text[:500] 
    }
    logs.insert(0, new_log) 
    save_json_to_azure(logs[:100], AZURE_ERROR_LOG_BLOB) 
    return new_log

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
        if resp.status_code != 200: return None, []
        soup = BeautifulSoup(resp.content, 'html.parser')
        desc_div = soup.find('div', class_=re.compile(r'description', re.I))
        desc = desc_div.get_text(strip=True)[:2000] if desc_div else ""
        
        images = []
        for img in soup.find_all('img', class_=re.compile(r'gallery', re.I)):
            if img.get('src'): images.append(img.get('src'))
        
        return desc, images[:3] 
    except: return None, []

def scrape_printables_details(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200: return None, []
        soup = BeautifulSoup(resp.content, 'html.parser')
        desc_div = soup.find('div', {'id': 'description'})
        if not desc_div: desc_div = soup.find('div', class_=re.compile(r'description', re.I))
        desc = desc_div.get_text(strip=True)[:2000] if desc_div else ""
        
        images = []
        for img in soup.find_all('img'):
            src = img.get('src')
            if src and 'media.printables.com' in src:
                images.append(src)
        
        return desc, images[:3]
    except: return None, []

def evaluate_insert_with_ai(game_name, search_url, site, status_container=None):
    api_key = st.secrets.get("google_api_key")
    if not api_key: return 0, "Missing API Key", "", None

    details_text = ""
    if site == "Thingiverse" and "thingiverse.com/thing:" in search_url:
        details_text, images = scrape_thingiverse_details(search_url)
    elif site == "Printables" and "printables.com/model" in search_url:
        details_text, images = scrape_printables_details(search_url)
    
    context = f"Game: {game_name}. Site: {site}. URL: {search_url}. "
    if details_text: context += f"Description Snippet: {details_text}"
    else: context += "I cannot scrape the full page content directly."

    prompt = (
        f"{context}\n\n"
        "Evaluate the likely quality and utility of a 3D printed insert for this board game. "
        "Consider factors like: does this game need an insert? Are there known good designs? "
        "If you have description text above, analyze it for keywords like 'sleeved cards', 'vertical storage', 'lid lift'. "
        "Also, try to infer the filament colors used or recommended from the description (e.g. 'printed in black and red'). "
        "Provide a JSON response with:\n"
        "- score: (integer 1-10, where 10 is essential/perfect design)\n"
        "- summary: (short 1-sentence summary of why)\n"
        "- colors: (string, inferred colors or 'Unknown')\n"
        "If you have absolutely no info, guess a conservative 5."
    )
    
    headers = {"Content-Type": "application/json"}
    data = {"contents": [{"parts": [{"text": prompt}]}]}

    last_error = ""

    for model_name in MODELS_TO_TRY:
        if status_container:
            status_container.info(f"Trying AI Model: **{model_name}**...")
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        try:
            response = requests.post(url, headers=headers, json=data)
            if response.status_code == 200:
                result = response.json()
                text = result['candidates'][0]['content']['parts'][0]['text']
                if "```json" in text: text = text.split("```json")[1].split("```")[0]
                elif "```" in text: text = text.split("```")[1].split("```")[0]
                data = json.loads(text)
                return data.get("score", 5), data.get("summary", "No summary."), data.get("colors", ""), model_name
            elif response.status_code == 404 or response.status_code == 429:
                log_error_to_azure(game_name, model_name, response.status_code, response.text)
                last_error = f"{response.status_code} ({model_name})"
                continue 
            else:
                log_error_to_azure(game_name, model_name, response.status_code, response.text)
                return 5, f"AI API Error ({model_name}): {response.status_code}", "", model_name
        except Exception as e:
            log_error_to_azure(game_name, model_name, "Exception", str(e))
            last_error = str(e)
            continue

    return 5, f"AI Error: All models failed. Last: {last_error}", "", None

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
    return f"https://makerworld.com/en/search/models?keyword={search_term}", "MakerWorld"

def process_ai_evaluations(results_list, limit=20, delay=5, retry_on_429=False):
    count = 0
    updated = False
    
    if not retry_on_429 and st.session_state.get("batch_run_complete", False):
        return results_list, False

    progress_bar = st.progress(0)
    status_text = st.empty()
    model_status = st.empty() # New container for model status
    
    fallback_warnings = []

    for i, item in enumerate(results_list):
        if count >= limit: break
        
        needs_eval = not item.get("AI_Evaluated", False)
        if not needs_eval and any(x in str(item.get("AI_Summary", "")) for x in ["AI Config Error", "AI Error", "AI API Error", "AI Setup Error", "AI Rate Limit"]):
            needs_eval = True

        if needs_eval:
            status_text.text(f"Evaluating {item['Game Title']} with AI...")
            
            if item.get("Manual_URL"):
                candidate_url = item["Manual_URL"]
                site = "Manual"
                if "thingiverse" in candidate_url: site = "Thingiverse"
                elif "printables" in candidate_url: site = "Printables"
                elif "makerworld" in candidate_url: site = "MakerWorld"
            else:
                candidate_url, site = find_best_candidate(item['Game Title'])
            
            score, summary, colors, used_model = evaluate_insert_with_ai(item['Game Title'], candidate_url, site, model_status)
            
            if "Rate Limit" in str(summary):
                if retry_on_429:
                    status_text.warning("Rate Limit hit. Waiting 60s...")
                    time.sleep(60)
                    score, summary, colors, used_model = evaluate_insert_with_ai(item['Game Title'], candidate_url, site, model_status)
                    if "Rate Limit" in str(summary):
                        status_text.error("Rate Limit hit again. Stopping.")
                        break
                else:
                    status_text.warning("AI Rate Limit Reached. Stopping batch.")
                    break 
            
            if "AI Error" in str(summary):
                st.session_state.has_ai_error = True
            
            # Check for fallback usage
            if used_model and used_model != MODELS_TO_TRY[0]:
                fallback_warnings.append(f"Used fallback model **{used_model}** for *{item['Game Title']}*")

            item["AI_Score"] = score
            item["AI_Summary"] = summary
            item["AI_Evaluated"] = True
            item["Candidate_URL"] = candidate_url
            item["Priority_Score"] = item["Plays"] + item["AI_Score"]
            if colors and not item.get("Colors"): 
                item["Colors"] = colors
            
            updated = True
            count += 1
            progress_bar.progress(count / limit)
            time.sleep(delay) 
            
    if not retry_on_429:
        st.session_state.batch_run_complete = True
        
    if fallback_warnings:
        if "fallback_warnings" not in st.session_state: st.session_state.fallback_warnings = []
        st.session_state.fallback_warnings.extend(fallback_warnings)
        
    progress_bar.empty()
    status_text.empty()
    model_status.empty() # Clear model status
    return results_list, updated

# --- Main App ---
def main():
    st.set_page_config(layout="wide")
    st.title("Insert Curator")
    
    search_query = st.text_input("Search all games in your collection:", "")

    # Load Data
    printed_games_names = get_list_from_azure(AZURE_PRINTED_BLOB, "printed_games.txt")
    excluded_games = get_list_from_azure(AZURE_EXCLUDED_BLOB)
    collection_data = load_json_from_azure(AZURE_COLLECTION_BLOB)
    search_results = load_json_from_azure(AZURE_SEARCH_RESULTS_BLOB) or []

    # Display total games count
    if collection_data:
        st.write(f"Total games in collection: {len(collection_data)}")

    # Warnings & Alerts
    if st.session_state.get("has_ai_error", False):
        with st.expander("⚠️ AI Errors Detected", expanded=True):
            st.warning("Some AI evaluations failed. Check the logs below.")
            if st.button("View Error Logs"):
                logs = load_json_from_azure(AZURE_ERROR_LOG_BLOB)
                if logs: st.dataframe(logs)
                else: st.write("No logs found.")
            if st.button("Clear Error Alert"):
                st.session_state.has_ai_error = False
                st.rerun()
                
    if st.session_state.get("fallback_warnings"):
        with st.expander("ℹ️ AI Model Fallbacks", expanded=True):
            for w in st.session_state.fallback_warnings:
                st.info(w)
            if st.button("Clear Warnings"):
                st.session_state.fallback_warnings = []
                st.rerun()

    # Sidebar
    if st.sidebar.button("Refresh Collection from BGG"):
        st.session_state.batch_run_complete = False 
        collection = fetch_bgg_collection_from_api(BGG_USER)
        if collection:
            save_json_to_azure([g.to_dict() for g in collection], AZURE_COLLECTION_BLOB)
            st.rerun()
            
    # Manage Lists in Sidebar
    with st.sidebar.expander("Manage Lists"):
        st.write("### Already Printed")
        if printed_games_names:
            for g in printed_games_names:
                c1, c2 = st.columns([4, 1])
                c1.write(g)
                if c2.button("❌", key=f"del_print_{g}"):
                    printed_games_names.remove(g)
                    save_json_to_azure(printed_games_names, AZURE_PRINTED_BLOB)
                    st.rerun()
        else:
            st.write("None")
            
        st.divider()
        
        st.write("### Never Print (Excluded)")
        if excluded_games:
            for g in excluded_games:
                c1, c2 = st.columns([4, 1])
                c1.write(g)
                if c2.button("❌", key=f"del_excl_{g}"):
                    excluded_games.remove(g)
                    save_json_to_azure(excluded_games, AZURE_EXCLUDED_BLOB)
                    st.rerun()
        else:
            st.write("None")

    # Bulk AI Processing
    with st.sidebar.expander("AI Bulk Processing"):
        bulk_qty = st.number_input("Games to Process", min_value=1, max_value=100, value=10)
        if st.button("Start Bulk Processing"):
            st.session_state.bulk_processing = True
            st.session_state.bulk_qty = bulk_qty

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
        
        # Apply search filter
        if search_query:
            games = [game for game in games if search_query.lower() in game.name.lower()]

        # Separate printed games
        printed_games_full = [g for g in games if g.name in printed_games_names]
        games = [g for g in games if g.name not in printed_games_names]

        cutoff = datetime.now() - timedelta(days=DAYS_SINCE_LAST_PLAY)
        
        priority_games = [
            g for g in games 
            if g.last_played and g.last_played > cutoff 
            and g.name not in excluded_games
        ]
        
        if not priority_games and not search_query: # Don't show this if user is searching
            priority_games = sorted(
                [g for g in games if g.name not in excluded_games], 
                key=lambda x: x.num_plays, 
                reverse=True
            )[:50]
        
        cached_map = {item["Game Title"]: item for item in search_results}
        final_list = []
        
        for game in priority_games:
            if game.name in cached_map:
                existing = cached_map[game.name]
                existing["Plays"] = game.num_plays
                existing["Last Played"] = game.last_played.strftime('%Y-%m-%d') if game.last_played else "N/A"
                
                if "AI API Error" in str(existing.get("AI_Summary", "")) and "404" in str(existing.get("AI_Summary", "")):
                    existing["AI_Evaluated"] = False
                    existing["AI_Score"] = 0
                    existing["AI_Summary"] = "Pending Retry..."
                
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
                    "Search URL": f"https://makerworld.com/en/search/models?keyword={urllib.parse.quote_plus(game.name + ' insert')}",
                    "Manual_Priority": False # Default
                })
        
        final_list.sort(key=lambda x: (x.get("Manual_Priority", False), x["Priority_Score"]), reverse=True)
        
        # Handle Bulk Processing Trigger
        if st.session_state.get("bulk_processing", False):
            qty = st.session_state.get("bulk_qty", 10)
            st.info(f"Starting bulk processing of {qty} games... This may take a while.")
            final_list, updated = process_ai_evaluations(final_list, limit=qty, delay=20, retry_on_429=True)
            if updated:
                save_json_to_azure(final_list, AZURE_SEARCH_RESULTS_BLOB)
            st.session_state.bulk_processing = False
            st.success("Bulk processing complete!")
            st.rerun()

        # Normal Batch AI Evaluation (on load)
        if not search_query: # Don't run AI evals when searching
            final_list, updated = process_ai_evaluations(final_list, limit=10, delay=5)
            if updated:
                save_json_to_azure(final_list, AZURE_SEARCH_RESULTS_BLOB)

        st.subheader(f"Top Games to Find Inserts For ({len(final_list)} shown)")
        
        if not final_list and search_query:
            st.warning(f"No games found matching '{search_query}'.")
        elif not final_list:
            st.info("No priority games to display.")

        for i, item in enumerate(final_list):
            # Expander Header
            priority_icon = "⭐ " if item.get("Manual_Priority") else ""
            header_text = f"#{i+1} {priority_icon}**{item['Game Title']}** | Plays: {item['Plays']} | Priority: {item['Priority_Score']}"
            
            with st.expander(header_text, expanded=False):
                c1, c2, c3 = st.columns([2, 3, 1])
                
                with c1:
                    st.markdown("### Model Link")
                    current_url = item.get('Manual_URL') or item.get('Candidate_URL') or item['Search URL']
                    st.markdown(f"🔗 [Open Model Page]({current_url})")
                    
                    new_url = st.text_input("Manual Model Link", value=item.get('Manual_URL', ''), key=f"url_{i}")
                    if st.button("Save Link", key=f"save_url_{i}"):
                        item['Manual_URL'] = new_url
                        item['Candidate_URL'] = new_url 
                        item['AI_Evaluated'] = False 
                        save_json_to_azure(final_list, AZURE_SEARCH_RESULTS_BLOB)
                        st.rerun()

                with c2:
                    st.markdown("### AI Analysis")
                    st.metric("Quality Score", f"{item['AI_Score']}/10")
                    st.info(item['AI_Summary'])
                    
                    st.markdown("### Colors")
                    colors = st.text_input("Colors Used", value=item.get('Colors', ''), key=f"colors_{i}")
                    if colors != item.get('Colors', ''):
                        item['Colors'] = colors
                        save_json_to_azure(final_list, AZURE_SEARCH_RESULTS_BLOB)

                with c3:
                    st.markdown("### Actions")
                    
                    is_priority = item.get("Manual_Priority", False)
                    btn_label = "Unset Priority" if is_priority else "⭐ Set Top Priority"
                    if st.button(btn_label, key=f"prio_{i}"):
                        item["Manual_Priority"] = not is_priority
                        save_json_to_azure(final_list, AZURE_SEARCH_RESULTS_BLOB)
                        st.rerun()
                        
                    if st.button("✅ Printed", key=f"print_{i}", help="Mark as Printed"):
                        printed_games_names.append(item['Game Title'])
                        save_json_to_azure(printed_games_names, AZURE_PRINTED_BLOB)
                        new_results = [r for r in final_list if r['Game Title'] != item['Game Title']]
                        save_json_to_azure(new_results, AZURE_SEARCH_RESULTS_BLOB)
                        st.rerun()
                    
                    if st.button("🚫 Never Print", key=f"excl_{i}", help="Exclude from future lists"):
                        excluded_games.append(item['Game Title'])
                        save_json_to_azure(excluded_games, AZURE_EXCLUDED_BLOB)
                        new_results = [r for r in final_list if r['Game Title'] != item['Game Title']]
                        save_json_to_azure(new_results, AZURE_SEARCH_RESULTS_BLOB)
                        st.rerun()

                    if st.button("🔄 Re-Eval AI", key=f"reeval_{i}"):
                        with st.spinner("Re-evaluating..."):
                            candidate_url = item.get('Manual_URL')
                            site = "Manual"
                            if not candidate_url:
                                candidate_url, site = find_best_candidate(item['Game Title'])
                            
                            score, summary, colors, used_model = evaluate_insert_with_ai(item['Game Title'], candidate_url, site, None) # Pass None for status container here as it's inside a spinner
                            item["AI_Score"] = score
                            item["AI_Summary"] = summary
                            item["AI_Evaluated"] = True
                            item["Candidate_URL"] = candidate.url
                            item["Priority_Score"] = item["Plays"] + item["AI_Score"]
                            if colors: item["Colors"] = colors
                            save_json_to_azure(final_list, AZURE_SEARCH_RESULTS_BLOB)
                        st.rerun()

        # --- Display Printed Games ---
        if printed_games_full:
            st.subheader("Printed Games")
            for game in sorted(printed_games_full, key=lambda x: x.name):
                with st.expander(f"{game.name}"):
                    st.write("**Status: PRINTED**")
                    st.write(f"Plays: {game.num_plays}")
                    st.write(f"Last Played: {game.last_played.strftime('%Y-%m-%d') if game.last_played else 'N/A'}")


if __name__ == "__main__":
    main()
