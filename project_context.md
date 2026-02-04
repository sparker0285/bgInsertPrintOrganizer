# Project Context: Insert Curator

This file tracks the context, decisions, and progress of the "Insert Curator" project.

**Goal:** Build a Python Streamlit app to cross-reference a user's BoardGameGeek (BGG) collection with 3D print repositories to find high-quality board game inserts.

## Key Decisions & User Preferences

- **3D Print Site Priority:**
  1. MakerWorld.com
  2. Thingiverse.com
  3. Printables.com
- **Game Prioritization:**
  - High priority on games played recently (`last_played` date is available).
  - If `last_played` is not available, the game is low priority.
  - The app should eventually consider community recommendations (from BGG forums, Reddit, etc.) to define "good" inserts, but for now, it will use on-site metrics like downloads, likes, and makes.
- **Exclusion List:** A file named `printed_games.txt` will be used to exclude games for which inserts have already been printed.
- **Workflow:** 
  - The agent should **not** automatically run the Streamlit application after making file changes. It should only save the files and wait for an explicit request to run the app.
  - When asked to run the app, the agent should use `Start-Process` in PowerShell to run Streamlit in the background.
- **GitHub Reference:** The user has a repository named `BGPicker_webapp` on their GitHub account that can be used as a reference for interacting with BGG APIs.
- **Data Persistence:** The app now uses Azure Blob Storage to cache the BGG collection. This avoids frequent API calls and potential authentication issues. The user provides an Azure Storage connection string in `secrets.toml`.

## Current Status

- The `boardgamegeek2` dependency issue has been resolved by switching to direct `requests` calls to the BGG API.
- The app is now encountering a `401 Unauthorized` error when fetching BGG data, indicating an API key is required.
- The next step is to get the user's GitHub repository URL to understand how to implement the API key.
- The project has been initialized with `bgInsertPrintOrganizer.py`, `requirements.txt`, and `printed_games.txt`.
- A virtual environment `.venv` has been created.
- The application was facing a persistent `ModuleNotFoundError: No module named 'boardgamegeek2'`.
- **Resolution:** The `boardgamegeek2` dependency has been removed from `requirements.txt` and the application has been rewritten to use the `requests` library and the BGG XML API v2 directly, resolving the environment issue.
- **Update:** Added `pandas` to `requirements.txt`.
- **Issue:** User reported `WinError 2` during pip install and `streamlit` command not found. This indicates the virtual environment is not activated or dependencies failed to install in the global scope.
- **Issue:** User encountered `PSSecurityException` when trying to activate the virtual environment.
- **Action:** Guiding user to change execution policy to allow script activation.
- **Issue:** User is getting a `401 Unauthorized` error when fetching the BGG collection.
- **Attempt 1:** Added `User-Agent` header to the request, as BGG often blocks requests without it.
- **Result:** User still reports 401.
- **Attempt 2:** Modified code to try using the API key from `secrets.toml` if the initial request fails. The code now attempts to send the key as a query parameter (`apikey` or `key`) or as a Bearer token in the header. This is a "shot in the dark" approach since the XML API v2 is officially public, but maybe the user is hitting a specific restriction or using a proxy.
- **Result:** The user got past the 401 error (or the code proceeded despite it, or the retry worked), but now hit an `AttributeError: 'NoneType' object has no attribute 'text'` at `last_played_str = item.find('lastmodified').text`.
- **Analysis:** This means `item.find('lastmodified')` returned `None`, so calling `.text` on it failed. This is unexpected because `lastmodified` is usually present in BGG collection items. However, the XML structure might vary.
- **Fix:** I need to add a check for `None` before accessing `.text` for `lastmodified` and other fields.
- **New Feature:** User requested to save the collection to Azure Storage to avoid constant API calls and potential auth issues.
- **Implementation:** Added `azure-storage-blob` to `requirements.txt`. Updated `bgInsertPrintOrganizer.py` to:
    1. Check Azure Storage for `collection.json`.
    2. If found, load it.
    3. If not found or "Refresh" is clicked, fetch from BGG API (using the key) and save to Azure.
    4. Added robust `None` checking for XML parsing.
- **Issue:** User reports `ModuleNotFoundError: No module named 'azure'`.
- **Cause:** The user likely didn't run `pip install -r requirements.txt` after I added `azure-storage-blob` to it, or the installation failed/wasn't in the active venv.
- **Action:** Remind user to install dependencies.
- **Issue:** User reports `Failed to fetch BGG collection. Status code: 401` again, with empty response content.
- **Analysis:** The previous fix for 401 (trying different auth methods) was overwritten or not robust enough. The user insists the API key is required. I need to systematically try all common ways to pass an API key (query param `apikey`, `key`, header `Authorization`, `X-API-Key`) and log which one works or fails.
- **Action:** I've updated `fetch_bgg_collection_from_api` to iterate through a list of auth strategies and report success/failure for each. This will help debug exactly which method (if any) is accepted.
- **Issue:** App now runs and saves to Azure, but reports "No games played in the last 365 days". User says this is incorrect and that play information needs to be fetched properly.
- **Analysis:** The current code looks for `lastplayed` in the `stats` tag or `lastmodified`. If the user has played games recently but the API isn't returning it in the `collection` endpoint, we might need to fetch plays separately or use a different parameter. The user mentioned they have another app that does this correctly.
- **Action:** Ask the user for the example code or repository they mentioned to see how they fetch play data.
- **Action:** User provided the repo URL: `https://github.com/sparker0285/BGPicker_webapp.git`.
- **Constraint:** I cannot run `git clone`. I can only run specific git commands on the current repo.
- **Alternative:** I will ask the user to clone it or provide the file content, OR I can try to guess based on common BGG API usage.
- **Wait:** I can't clone external repos. I should ask the user to provide the relevant file content or explain how they did it.
- **Actually:** The user said "I can give you an example... I fixed this in a conversation with you yesterday". This implies I might have access to previous context or they expect me to know. But I don't have access to previous conversations outside this session.
- **Strategy:** I will explain I can't clone the repo and ask them to paste the relevant function (likely `get_plays` or similar) or I can try to fetch plays from the `/plays` endpoint which is the standard way to get play history if it's not in the collection.
- **Hypothesis:** The `collection` endpoint only updates `lastplayed` if the user logs the play *and* links it to their collection item correctly, or maybe it's just slow. The `/plays` endpoint is the definitive source for play history.
- **Update:** User offered to drop the file in the workspace. This is the best option.
- **Analysis of `bgpickerapp_api.py`:**
    - It uses `requests.Session()` with headers: `{"Authorization": f"Bearer {BGG_API_TOKEN}", "User-Agent": "StreamlitGamePicker/12.1", "Accept": "application/xml"}`.
    - **Crucially**, it uses `fetch_full_play_history(username)` which calls `https://boardgamegeek.com/xmlapi2/plays?username={username}&page={page}`.
    - It iterates through pages of plays to build a full history.
    - It does *not* rely on the `collection` endpoint for play dates, but rather fetches plays separately and likely merges or uses them for stats.
    - The `fetch_from_api` function (for collection) *does* try to read `numplays` from the collection item, but it doesn't seem to rely on `lastplayed` from there for the "last played" logic in the same way.
    - **Key Takeaway:** To get accurate "last played" dates, I must fetch the play history from `/plays` and map the most recent play date to each game in the collection.
- **Implementation:** Updated `bgInsertPrintOrganizer.py` to include `fetch_play_history` which iterates through the first 5 pages of plays (to keep it fast but get recent stuff) and updates the `last_played` date for games in the collection. It also uses the correct `Bearer` token auth.
