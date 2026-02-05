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
- **Status:** User confirms the app works now.
- **New Request:** Add a button to the results grid to add a game to the "Already Printed" list. This list should be saved to Azure (or local file) and loaded on startup.
- **Plan:**
    1.  Modify `get_printed_games` and `save_printed_games` to use Azure Storage (similar to `collection.json`). Let's call it `printed_games.json`.
    2.  Update the UI to display the search results not just as a static dataframe, but as a list of items with an "Add to Printed" button for each. Streamlit's `st.dataframe` doesn't support buttons inside cells easily. I might need to use `st.data_editor` (with a boolean column) or render rows manually with `st.columns`.
    3.  Given the requirement "button to the grid of results", `st.data_editor` with a checkbox column "Printed?" is the most modern Streamlit way. When the user checks it, I can detect the change and update the list.
    4.  Alternatively, I can render a button next to each row if I iterate through them.
    5.  Let's go with `st.data_editor` if possible, or a simple "Add" button next to the game title if I render them as cards/rows.
    6.  Actually, the user said "button to the grid of results". A dataframe with a checkbox column is probably the cleanest "grid" approach.
    7.  Wait, `st.data_editor` allows editing. If I add a "Printed" boolean column, the user can check it. Then I need a "Save" button or auto-save logic.
    8.  Let's try to make it seamless.
    9.  Also, need to migrate the existing `printed_games.txt` logic to Azure if the user wants it there.
- **Update:** User clarified they want to persist the "Top Games to Find Inserts For" list to Azure as well, to avoid re-running queries.
- **Implementation:**
    - Added `AZURE_SEARCH_RESULTS_BLOB = "search_results.json"`.
    - Added `AZURE_PRINTED_BLOB = "printed_games.json"`.
    - Implemented `save_json_to_azure` and `load_json_from_azure` generic helpers.
    - Updated `main()` to:
        - Load `printed_games` from Azure (migrating from txt if needed).
        - Load `search_results` from Azure if not refreshing.
        - If refreshing or no cache, run the search and save to Azure.
        - Display results using `st.data_editor` with a "Printed?" checkbox column.
        - When "Printed?" is checked:
            - Add game to `printed_games` list and save to Azure.
            - Remove game from `search_results` list and save to Azure.
            - Rerun the app to refresh the view.
- **Status:** User confirms checkbox works.
- **New Request:**
    - Remove "Result Count" column.
    - Add a "Priority Score" metric.
    - Use Gemini AI (free tier) to evaluate insert quality based on description and comments.
    - **Logic:**
        1.  Sort games by Play Count (heavy weight).
        2.  For the top 20 games that haven't been evaluated yet:
            - Find the "best" candidate insert (e.g., most downloads) from MakerWorld/Thingiverse/Printables.
            - Send its description/comments to Gemini.
            - Get a quality score (1-10) and sentiment summary.
        3.  Save this AI evaluation to Azure so it's not re-run.
        4.  Formula: Play Heavy (e.g., Plays + AI Score).
        5.  UI: Add a "Re-evaluate" button for individual rows.
        6.  Process: Automatically grab the next 20 unevaluated games on each run.
- **Implementation:**
    - Added `google-generativeai` to `requirements.txt`.
    - Updated `bgInsertPrintOrganizer.py`:
        - Added `evaluate_insert_with_ai` function using Gemini.
        - Added `scrape_thingiverse_details` and `scrape_printables_details` (basic scraping).
        - Added `find_best_candidate` to try and find a specific model URL (prioritizing Thingiverse for scraping ease, but defaulting to MakerWorld search if needed).
        - Implemented batch processing (20 items) in `process_ai_evaluations`.
        - Updated UI to use `st.columns` for a custom row layout (Game Link, Plays, Score, AI Score, Summary, Done Button, Re-Eval Button).
        - Removed `st.data_editor` in favor of this custom layout to support the "Re-eval" button requirement.
- **Issue:** User reports `NameError: name 'get_printed_games' is not defined`.
- **Cause:** I accidentally removed the `get_printed_games` function definition when refactoring the code, but I'm still calling it in `main()`.
- **Fix:** I need to restore the `get_printed_games` function.
- **Issue:** User reports `Gemini Config Error: module 'google.generativeai' has no attribute 'GenerativeModel'`.
- **Cause:** This usually happens if the installed version of `google-generativeai` is too old or if there's a namespace conflict. The `GenerativeModel` class was introduced in newer versions (0.3.0+).
- **Action:** I should check the installed version or try to upgrade it. Since I can't check the version easily, I'll assume I need to force an upgrade or use the older API style if the environment is restricted. However, `GenerativeModel` is the standard way now.
- **Alternative:** It's possible the user has an old version installed globally or in the venv.
- **Fix:** I will ask the user to upgrade the package.
- **Wait:** I can also try to use `genai.configure` and then `genai.generate_text` (legacy) if `GenerativeModel` isn't found, but it's better to get the right version.
- **Actually:** The error `module 'google.generativeai' has no attribute 'GenerativeModel'` is very specific. It means the import worked but the class isn't there.
- **Hypothesis:** The installed version is < 0.3.0.
- **Plan:** Ask user to run `pip install --upgrade google-generativeai`.
- **Issue:** User says "In installed google-generativeai and I still get the exact same error".
- **Analysis:** This is strange. It might be a caching issue, or the user is running the command in the wrong environment (not the `.venv`). Or maybe `google-generativeai` is conflicting with another package.
- **Alternative Fix:** I can switch to the legacy API call `genai.chat` or `genai.generate_text` if available, OR I can try to debug the environment.
- **Better Fix:** I'll try to use `genai.configure` and then check what's available. But since I can't interactively debug, I should probably try to use the older API method as a fallback if `GenerativeModel` fails.
- **Wait:** The older API uses `genai.generate_text`.
- **Let's try this:** I will modify the code to try `GenerativeModel` first, and if that fails (AttributeError), fall back to `genai.generate_text` or similar.
- **Actually:** If the user just installed it, maybe they need to restart the Streamlit server? They probably did.
- **Let's check `pip list`** if I could, but I can't.
- **Hypothesis:** Maybe the package name is `google-generativeai` but the import is `google.generativeai`. That is correct.
- **Maybe:** The user has a file named `google.py` or `google/generativeai.py` in their project that is shadowing the library? Unlikely in this structure.
- **Let's try the legacy method.** It's safer if the environment is stubborn.
- **Legacy Method:**
  ```python
  response = genai.generate_text(
      model='models/text-bison-001',
      prompt=prompt
  )
  return response.result
  ```
  But `gemini-pro` or `gemini-1.5-flash` requires the new API. If they have an old library, they can't use Gemini models easily.
- **Wait:** If they have a *very* old version, they might not even have `generate_text`.
- **Let's try to force a specific version in requirements.txt.** `google-generativeai>=0.5.0`.
- **Action:** Update `requirements.txt` to force a newer version, and ask user to install again. This is the most robust fix. If they just ran `pip install google-generativeai`, it might have satisfied a cached requirement.
- **Issue:** User still gets the error after forcing reinstall.
- **Action:** Document the issue in `project_context.md` as requested.
- **Next Steps (for later):**
    1.  Verify python environment (is `.venv` actually active?).
    2.  Check for file shadowing (e.g., a local `google.py`).
    3.  Try a completely clean venv.
    4.  Fallback to `requests` call to Gemini API REST endpoint directly if the SDK is broken.
- **Update:** User provided `bowlingAssistantApp.py` which uses `google.generativeai` successfully.
- **Analysis of `bowlingAssistantApp.py`:**
    - It imports `google.generativeai as genai`.
    - It calls `genai.configure(api_key=api_key)`.
    - It calls `model = genai.GenerativeModel('models/gemini-flash-latest')`.
    - It calls `response = model.generate_content(prompt)`.
    - **Crucially:** This code is *identical* to what I wrote in `bgInsertPrintOrganizer.py`.
    - **Conclusion:** If `bowlingAssistantApp.py` works in the *same environment*, then my code should work. If it doesn't, there must be a subtle difference or the user is running them in different environments.
    - **Wait:** The user said "Look at how this app is able to use the Gemini AI and replicate that here."
    - **Observation:** The model name used in the example is `'models/gemini-flash-latest'`. I used `'gemini-1.5-flash'`.
    - **However:** The error is `module 'google.generativeai' has no attribute 'GenerativeModel'`. This error happens *before* the model name is even used. It happens at the class instantiation or reference.
    - **Wait:** Is it possible `bowlingAssistantApp.py` is running in a different environment? The user said "I added bowlingAssistantApp.py to the examples folder". They didn't say they *ran* it successfully *in this session*. They just said "Look at how this app is able to use...".
    - **Hypothesis:** The user *thinks* it works or it worked elsewhere. But the error `AttributeError: module 'google.generativeai' has no attribute 'GenerativeModel'` is definitive: the installed library version does not have that class.
    - **Wait:** Maybe the user has a file named `google.py` in their project root? I checked the file list earlier and didn't see it.
    - **Let's check `bgInsertPrintOrganizer.py` imports again.**
      ```python
      import google.generativeai as genai
      ```
      And usage:
      ```python
      return genai.GenerativeModel('gemini-1.5-flash')
      ```
    - **Let's check `bowlingAssistantApp.py` imports.**
      ```python
      import google.generativeai as genai
      ```
      And usage:
      ```python
      model = genai.GenerativeModel('models/gemini-flash-latest')
      ```
    - **It is identical.**
    - **Maybe:** The user has `google` namespace package issues.
    - **Plan:** I will try to use the `requests` library to call the Gemini API directly via REST. This bypasses the python library version issues entirely. This is a robust fallback.
    - **API Endpoint:** `https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={API_KEY}`.
    - **Payload:** `{"contents": [{"parts": [{"text": prompt}]}]}`.
- **Status:** Switched to REST API. User says app is running but:
    1.  Evaluating *all* games, not just top 20.
    2.  AI Summary shows "AI Config Error".
    3.  Button says "Done", wants "Printed".
    4.  Link is merged with title, wants separate column.
    5.  Wants collapsible rows (expander) for details.
    6.  Wants a button in config to pop open printed list (instead of just sidebar expander?).
- **Analysis of "AI Config Error":**
    - The code checks `if not api_key: return 0, "Missing API Key"`.
    - If it returns "AI Config Error", it means `evaluate_insert_with_ai` failed inside the `try/except` block or `api_key` was missing but handled differently?
    - Wait, I see `return 5, f"AI Error: {str(e)[:50]}"` in the exception handler.
    - If it says "AI Config Error", where is that string?
    - Ah, in the *previous* version (using library) it was `if not model: return 0, "AI Config Error"`.
    - In the *current* REST version, I don't see "AI Config Error" string.
    - **Wait:** The user might be seeing cached results from the *previous* run (when the library failed).
    - **Fix:** I need to clear the cache or force re-evaluation if the summary is "AI Config Error".
- **Analysis of "Evaluating All Games":**
    - `process_ai_evaluations` has `if count >= limit: break`.
    - But if `st.rerun()` happens, it reloads.
    - If `save_json_to_azure` works, the `AI_Evaluated` flag should be true.
    - If the user sees it evaluating *all*, maybe the save isn't working, or the loop logic is flawed.
    - **Correction:** I implemented the "infinite loop" fix plan: use `st.session_state` to track if batch has run.
- **UI Changes:**
    - Use `st.expander` for each game row.
    - Title of expander: `Game Name | Plays: X | Priority: Y`.
    - Inside expander:
        - Columns:
            - Col 1: Link to Model (separate).
            - Col 2: AI Score & Summary.
            - Col 3: Buttons (Printed, Re-Eval).
    - Change "Done" to "Printed".
    - Add "Show Printed Games" button in sidebar (or main area?) -> User said "in the config area".
- **Implementation:**
    - Updated `bgInsertPrintOrganizer.py` to incorporate all UI changes and the infinite loop fix.
    - Restored `get_printed_games` which was accidentally deleted.
    - Added logic to retry "AI Config Error" items.
- **Issue:** User reports `AI API Error: 404`.
- **Cause:** The REST API endpoint URL might be incorrect or the model name is wrong.
- **URL Used:** `https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}`
- **Verification:** The model name `gemini-1.5-flash` is correct for the Python SDK, but for the REST API, it might be `gemini-1.5-flash-latest` or just `gemini-1.5-flash`.
- **Wait:** The 404 usually means "Model not found" or "Method not found".
- **Let's check the docs (mental check):** The endpoint is `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`.
- **Maybe:** The model name needs to be `gemini-1.5-flash-latest` or `gemini-pro`.
- **Let's try `gemini-1.5-flash-latest`** as used in the user's example (`models/gemini-flash-latest`).
- **Wait:** The user's example used `models/gemini-flash-latest`.
- **Correction:** I should use `gemini-1.5-flash-latest` or `gemini-1.5-flash`.
- **Actually:** 404 can also mean the API key is invalid for that specific endpoint/model (though usually that's 403).
- **Let's try a safer model name:** `gemini-pro` is the most standard. Or `gemini-1.5-flash`.
- **Wait:** The user's example code used `genai.GenerativeModel('models/gemini-flash-latest')`. This maps to `models/gemini-flash-latest` in the API.
- **So the URL should be:** `https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent`.
- **Wait:** I used `gemini-1.5-flash`. Maybe that alias doesn't exist in the REST API directly without `models/` prefix?
- **Let's try:** `https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent`.
- **If that failed (404),** maybe I need to use `gemini-pro`.
- **Plan:** I will update the code to try a few known model names if the first one fails. Or just switch to `gemini-pro` which is usually available.
- **Better Plan:** Use `gemini-1.5-flash` but ensure the URL is correct.
- **Wait:** The error might be because I didn't include `models/` in the path variable but the API expects it? No, the docs say `models/{model}`.
- **Let's try `gemini-1.5-flash-latest`**.
- **Update:** User still gets 404.
- **Action:** I've updated the code to try a list of models: `gemini-1.5-flash`, `gemini-1.5-pro`, `gemini-1.0-pro`. This should cover the bases.
- **Issue:** User reports `AI API Error (models/gemini-flash-latest): 429`.
- **Cause:** 429 means "Too Many Requests". The user is hitting the rate limit of the free Gemini API tier.
- **Analysis:** The code processes 20 items in a loop with `time.sleep(1)`. This might be too fast for the free tier, or the user has already exhausted their quota for the minute/day.
- **Fix:** Increase the sleep time between requests. The free tier has a limit of 15 requests per minute (RPM).
- **Calculation:** 60 seconds / 15 requests = 4 seconds per request.
- **Plan:** Increase `time.sleep(1)` to `time.sleep(5)` to be safe (12 RPM).
- **Also:** Handle 429 gracefully by stopping the batch early instead of erroring out all subsequent items.
- **New Request:**
    - Add "Never Print" option to exclude games.
    - Store "Never Print" list in Azure (`excluded_games.json`).
    - Allow removing items from both "Printed" and "Never Print" lists via UI.
    - Sidebar management for these lists.
- **Implementation:**
    - Added `AZURE_EXCLUDED_BLOB`.
    - Added `get_list_from_azure` helper.
    - Updated `main` to load excluded list and filter priority games.
    - Added "Never Print" button to game row.
    - Added "Manage Lists" expander in sidebar with delete buttons.
- **Issue:** MakerWorld links are 404.
- **Cause:** The search URL format `https://makerworld.com/en/search?keyword=...` might be outdated or incorrect.
- **Fix:** Updated to `https://makerworld.com/en/search/models?keyword=...`.
- **New Request:**
    - Add ability to manually paste a "good model link" for a game.
    - This should override the auto-discovered search link.
    - **Plan:**
        - Add a text input field inside the game expander: "Manual Model Link".
        - Add a "Save Link" button.
        - When saved, update the `Candidate_URL` (or a new field `Manual_URL`) in the game's data structure.
        - Save to Azure.
        - Use this manual URL for the "Open Model Page" link and for future AI evaluations (if re-eval is clicked).
        - **UI:** Inside the expander, maybe below the current link or in a new column/section.
- **New Request:**
    - Add "Colors Used" tracking for each game.
    - **Question:** Can this be extracted from model files?
    - **Answer:** Not easily from just a URL or description. 3D model files (STL/3MF) don't inherently have "colors" unless it's a multi-color 3MF (like Bambu/MakerWorld). Even then, parsing that from a URL without downloading and inspecting the file is very hard/impossible via simple scraping.
    - **Alternative:** The user likely needs to manually enter this, OR we can ask the AI to infer it from the description/images (if we could see images).
    - **Plan:** Add a manual text input/multiselect for "Colors Used" in the expander.
    - **Refinement:** User asked "Is that information that you can get from the model files themselves?".
    - **Response:** I should clarify that it's difficult to automate reliably. I will add a manual field for it.
    - **Implementation:**
        - Add `Colors` field to `BggGame` or the dictionary in `search_results`.
        - Add UI in expander to edit/save colors.
        - Maybe a multiselect with common colors (Black, White, Grey, Red, Blue, etc.) + "Other".
- **New Request:**
    - Reduce batch size to 10.
    - Add a "Run AI Updates" button in config.
    - When clicked, ask how many games to process (number input).
    - Run loop with 20s delay.
    - Handle 429: wait 60s, retry once, then stop if failed again.
    - This allows "bulk processing" in background.
    - Normal behavior: grab 10 games on load.
- **Implementation:**
    - Update `process_ai_evaluations` to accept `delay` and `retry_on_429` params.
    - Update `main` to call `process_ai_evaluations(limit=10, delay=5)` on load.
    - Add sidebar section "AI Bulk Processing".
    - Add number input "Games to Process" and button "Start Bulk Processing".
    - On button click: call `process_ai_evaluations(limit=user_limit, delay=20, retry_on_429=True)`.
    - Implement retry logic in `evaluate_insert_with_ai` or wrapper.
- **Status:** User confirms bulk processing works.
- **New Request:**
    - Wipe out API information for any game that shows "AI API Error: 404".
    - This forces a retry on the next run.
- **Implementation:**
    - In `main`, when iterating `priority_games`, check if `AI_Summary` contains "AI API Error" and "404".
    - If so, reset `AI_Evaluated` to `False`, `AI_Score` to 0, and `AI_Summary` to "Pending Retry...".
