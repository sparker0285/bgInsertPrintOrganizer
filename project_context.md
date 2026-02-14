# Project Context: Insert Curator

This file tracks the context, decisions, and progress of the "Insert Curator" project.

**Goal:** Build a Python Streamlit app to cross-reference a user's BoardGameGeek (BGG) collection with 3D print repositories to find high-quality board game inserts.

## Key Decisions & User Preferences

- **3D Print Site Priority:**
  1. MakerWorld.com
  2. Thingiverse.com
  3. Printables.com
- **Game Prioritization:**
  - The app uses a "Priority Score" to rank games.
  - The score is a weighted combination of total play count (60% weight) and recency of play (40% weight).
  - The top 10 games based on this score are recommended.
- **Insert Quality:**
  - The app attempts to find the "best" insert by scraping the number of "likes" from Thingiverse and Printables search results.
  - It provides a direct link to the insert with the most likes.
  - For MakerWorld, which uses dynamic loading, the app falls back to providing a link to the search results page.
- **Exclusion List:** A file named `printed_games.txt` is used to exclude games for which inserts have already been printed.
- **Secrets Management:** The BGG API Key is stored in and read from a `.streamlit/secrets.toml` file, which is excluded from Git via `.gitignore`.
- **Workflow:** 
  - The agent should **not** automatically run the Streamlit application after making file changes. It should only save the files and wait for an explicit request to run the app.
  - When asked to run the app, the agent should use `Start-Process` in PowerShell to run Streamlit in the background, using the full path to the executable in the `.venv` to avoid PATH issues.

## Current Status

- **Search Functionality:** A search bar has been added to allow users to search their entire BGG collection.
- **Printed Games Display:** Games listed in `printed_games.txt` are now displayed in a separate, expandable section at the bottom of the app, clearly marked as "PRINTED". They are sorted alphabetically.
- The application has been significantly refactored to implement the new priority-based recommendation engine.
- **Last Played Date:** The app now uses the BGG `plays` endpoint to get accurate "last played" dates, resolving an issue where recently played games were not being correctly identified.
- **Error Handling:** The XML parsing logic has been made more robust to handle cases where games in the BGG collection are missing data fields (like `lastmodified` or `numplays`), which was causing `AttributeError` crashes.
- **Authentication:** The app now correctly authenticates with the BGG API using a Bearer Token (API Key) provided via the `.streamlit/secrets.toml` file. This resolved the `401 Unauthorized` errors.
- **Environment:** The app is now consistently run using the Python virtual environment, resolving the "'streamlit' is not recognized" error.
- The app is currently running with the new logic for the user to evaluate.