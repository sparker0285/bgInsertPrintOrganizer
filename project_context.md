# Project Context: Insert Curator

This file tracks the context, decisions, and progress of the "Insert Curator" project.

**Goal:** Build a Python Streamlit app to cross-reference a user's BoardGameGeek (BGG) collection with 3D print repositories to find high-quality board game inserts.

## Key Decisions & User Preferences

- **3D Print Site Priority:**
  1. MakerWorld.com
  2. Thingiverse.com
  3. Printables.com
- **Game Prioritization:**
  - The app now displays all games from the user's collection, regardless of play date.
  - The list is sorted by a "Priority Score," which is a combination of the total play count and an AI-generated quality score for a potential insert.
  - A manual "Set as Top Priority" button allows overriding the default sort order.
- **Exclusion Lists:**
  - `printed_games.json`: Excludes games for which inserts have already been printed.
  - `excluded_games.json`: Excludes games the user never wants to see in the main list.
  - Both lists are managed in the app's sidebar and stored in Azure Blob Storage.
- **Workflow:** 
  - The agent should **not** automatically run the Streamlit application after making file changes. It should only save the files and wait for an explicit request to run the app.
  - When asked to run the app, the agent should use `Start-Process` in PowerShell to run Streamlit in the background.
- **Data Persistence & Caching:**
  - The app uses Azure Blob Storage to cache the BGG collection (`collection.json`), printed/excluded lists, and AI evaluation results (`search_results_v2.json`).
  - This prevents redundant BGG API calls and Gemini AI evaluations on subsequent app runs. AI results are only fetched for games that have not been evaluated before, unless a manual re-evaluation is triggered.

## Current Status

- **Feature: Search:** A search bar allows filtering the entire collection by name.
- **Feature: Comprehensive Game Lists:** The app now displays three distinct, expandable lists at the bottom of the page so that every game in the user's collection is visible in one of the sections:
    1.  **Top Games to Find Inserts For:** The main, prioritized list of games needing inserts.
    2.  **Printed Games:** A list of games already marked as printed.
    3.  **Never Print Games:** A list of games the user has chosen to permanently exclude.
- **Feature: Game Count:** The UI now displays the total number of games loaded from the BGG collection and the number of games shown in the main priority list.
- **Feature: AI Bulk Processing:** A feature in the sidebar allows the user to trigger AI evaluations for a large number of games at once, with appropriate delays to handle API rate limits.
- **Issue Resolution (Missing Games):** The primary reason for "missing" games was a filter that only showed games played in the last 365 days. This filter has been removed, and now all games (not marked as printed or excluded) are displayed in the main list.
- **AI Integration:** The app uses the Gemini API via direct REST calls to evaluate the quality of potential 3D printable inserts. It includes a model-fallback mechanism to handle rate-limiting and logs any API errors to Azure for debugging.
- **Authentication:** The app correctly authenticates with the BGG API using a Bearer Token (API Key) provided via the `.streamlit/secrets.toml` file.
- **Environment:** The app is consistently run using the Python virtual environment.

The application is now feature-complete based on the user's requests and is ready for use. Future work could involve further enhancements to the AI evaluation or UI refinements.