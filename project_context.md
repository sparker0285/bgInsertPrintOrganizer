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

## Current Status

- The `boardgamegeek2` dependency issue has been resolved by switching to direct `requests` calls to the BGG API.
- The app is now encountering a `401 Unauthorized` error when fetching BGG data, indicating an API key is required.
- The next step is to get the user's GitHub repository URL to understand how to implement the API key.
- The project has been initialized with `bgInsertPrintOrganizer.py`, `requirements.txt`, and `printed_games.txt`.
- A virtual environment `.venv` has been created.
- The application was facing a persistent `ModuleNotFoundError: No module named 'boardgamegeek2'`.
- **Resolution:** The `boardgamegeek2` dependency has been removed from `requirements.txt` and the application has been rewritten to use the `requests` library and the BGG XML API v2 directly, resolving the environment issue.
- The app is now ready to be tested by the user.
