# streamlit_app.py
# Dungeon GPT Lite: An interactive AI story generator with Streamlit, Gemini API, and Firestore.
# This version focuses on simplicity and easy deployment, using only Google Gemini models
# with adjustable safety settings for 'censored' and 'uncensored' modes.

import os
import json
import uuid # Used to generate a unique ID for each browser session for Firebase persistence

import streamlit as st
from dotenv import load_dotenv # For loading environment variables during local development

# Firebase Admin SDK for server-side interactions with Firestore
import firebase_admin
from firebase_admin import credentials, firestore

# --- Configuration & Environment Setup ---

# Load environment variables from .env file for local development.
# On Streamlit Cloud, these values will be sourced from Streamlit Secrets.
load_dotenv()

def get_config_value(key: str, default: any = None) -> str:
    """
    Retrieves a configuration value.
    Prioritizes Streamlit secrets (for cloud deployment), then local environment variables.
    """
    if key in st.secrets:
        return st.secrets[key]
    return os.getenv(key, default)

# Google Gemini API Key
GOOGLE_API_KEY = get_config_value("GOOGLE_API_KEY")

# Firebase Service Account Key as a JSON string
FIREBASE_SERVICE_ACCOUNT_KEY = get_config_value("firebase_service_account_key")
APP_ID = "dungeon-gpt-lite-app" # A unique identifier for this application's data in Firestore

# --- Firebase Admin SDK Initialization ---
@st.cache_resource # This decorator caches the function result, preventing re-initialization on app reruns
def initialize_firebase():
    """
    Initializes the Firebase Admin SDK.
    Returns a Firestore client instance if successful, otherwise None.
    """
    print("Attempting to initialize Firebase Admin SDK...") # Logging
    if not firebase_admin._apps: # Check if Firebase app is already initialized
        try:
            if not FIREBASE_SERVICE_ACCOUNT_KEY:
                st.error("Firebase Service Account Key not found. Please add it to Streamlit Secrets or your .env file.")
                print("Error: FIREBASE_SERVICE_ACCOUNT_KEY is empty.") # Logging
                return None
            
            # Parse the JSON string service account key into a Python dictionary
            cred_dict = json.loads(FIREBASE_SERVICE_ACCOUNT_KEY)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            st.sidebar.success("Firebase Admin SDK initialized.") # Use sidebar for non-critical status
            print("Firebase Admin SDK initialized successfully.") # Logging
            return firestore.client()
        except Exception as e:
            st.sidebar.error(f"Error initializing Firebase Admin SDK: {e}")
            print(f"Firebase Init Error: {e}") # Logging
            return None
    else:
        print("Firebase Admin SDK already initialized.") # Logging
        return firestore.client()

db = initialize_firebase()

# --- Google Gemini API Configuration ---
print(f"GOOGLE_API_KEY present: {bool(GOOGLE_API_KEY)}") # Logging
if GOOGLE_API_KEY:
    try:
        from google import generativeai

        # Default stringent safety settings for 'censored' mode
        _DEFAULT_SAFETY_SETTINGS = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ]

        # Less stringent safety settings for 'uncensored' mode (use with caution)
        _UNCENSORED_SAFETY_SETTINGS = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]

        generativeai.configure(api_key=GOOGLE_API_KEY)
        # Create two Gemini model instances with different safety settings
        # USING gemini-1.5-flash-latest AS CONFIRMED WORKING
        gemini_model_censored = generativeai.GenerativeModel('gemini-1.5-flash-latest', safety_settings=_DEFAULT_SAFETY_SETTINGS)
        gemini_model_uncensored = generativeai.GenerativeModel('gemini-1.5-flash-latest', safety_settings=_UNCENSORED_SAFETY_SETTINGS)
        
        st.sidebar.success("Gemini API configured for both modes.")
        print("Gemini API models initialized successfully.") # Logging
    except Exception as e:
        st.sidebar.error(f"Error configuring Gemini API: {e}. Check your API key.")
        print(f"Gemini API Config Error: {e}") # Logging
        gemini_model_censored = None
        gemini_model_uncensored = None
else:
    st.sidebar.warning("GOOGLE_API_KEY not set. AI generation will be disabled.")
    print("Error: GOOGLE_API_KEY is missing.") # Logging
    gemini_model_censored = None
    gemini_model_uncensored = None


# --- Session State Management ---
# Initialize Streamlit's session state variables. These persist across reruns.
if "story_history" not in st.session_state:
    st.session_state.story_history = []
if "current_mode" not in st.session_state:
    st.session_state.current_mode = 'censored' # Default AI response mode
if "temperature" not in st.session_state:
    st.session_state.temperature = 0.7 # Default AI creativity level
if "tone" not in st.session_state:
    st.session_state.tone = "Fantasy" # Default story genre/tone
if "user_id" not in st.session_state:
    # Generate a unique ID for this browser session.
    # This ID will be used as the document ID in Firestore for saving/loading data.
    st.session_state.user_id = str(uuid.uuid4())
    st.toast(f"New session started. Your user ID: {st.session_state.user_id[:8]}...")
    print(f"New session user ID generated: {st.session_state.user_id}") # Logging


# --- AI Inference Function (Gemini Only) ---
def generate_gemini_response(prompt: str, temperature: float, mode: str) -> str:
    """
    Generates a story continuation using the Google Gemini API.
    Selects the appropriate Gemini model instance based on the chosen mode.

    Args:
        prompt: The full context of the conversation to send to the AI.
        temperature: Controls the randomness of the output (0.0 for deterministic, 1.0 for creative).
        mode: The AI response mode ('censored' or 'uncensored').

    Returns:
        The AI-generated story continuation text, or an informative error message.
    """
    selected_model = None
    if mode == 'censored':
        selected_model = gemini_model_censored
    elif mode == 'uncensored':
        selected_model = gemini_model_uncensored
    
    if not selected_model:
        print(f"Error: selected_model for {mode} mode is None. Check Gemini API config.") # Logging
        return f"Error: Gemini API for '{mode}' mode is not configured. Check your GOOGLE_API_KEY."

    try:
        generation_config = {"temperature": temperature}
        print(f"Calling Gemini API for mode: {mode}, temperature: {temperature}") # Logging
        print(f"Prompt sent (first 200 chars): {prompt[:200]}...") # Logging
        response = selected_model.generate_content(prompt, generation_config=generation_config)
        
        # Check if the response actually contains text content
        if response and hasattr(response, 'text') and response.text:
            print(f"Gemini API call successful for {mode} mode.") # Logging
            return response.text
        elif response and hasattr(response, 'prompt_feedback') and response.prompt_feedback:
            # Handle cases where content is blocked by safety settings
            print(f"Gemini API call blocked for {mode} mode. Reason: {response.prompt_feedback.block_reason.name}") # Logging
            return f"AI response was blocked by safety settings. Reason: {response.prompt_feedback.block_reason.name}"
        else:
            print(f"Gemini API returned empty/unreadable response for {mode} mode. Response: {response}") # Logging
            return "AI returned an empty or unreadable response."

    except Exception as e:
        # Provide more specific error messages for common Gemini API issues
        error_message = str(e)
        print(f"Gemini API call failed for {mode} mode. Exception: {e}") # Logging
        if "404" in error_message and "models/gemini-pro" in error_message: # This specific error should ideally not appear now
            return (f"AI (Gemini {mode}) API Error: Model 'gemini-pro' not found or accessible. "
                    "Ensure Generative Language API is enabled in your Google Cloud Project "
                    "and your GOOGLE_API_KEY is correct and has the necessary permissions.")
        elif "403" in error_message:
            return f"AI (Gemini {mode}) API Error: Permission denied. Check your GOOGLE_API_KEY and its permissions."
        elif "500" in error_message:
            return f"AI (Gemini {mode}) API Error: Internal server error. Please try again later."
        else:
            st.error(f"Error calling Gemini API for '{mode}' mode: {e}")
            return f"AI (Gemini {mode}) encountered an error: {e}"


# --- Firebase Firestore Interaction Functions ---

def save_story_to_firestore():
    """
    Saves the current story history and AI settings to Firestore.
    Each user's current session is saved under a unique document ID.
    """
    print(f"Attempting to save session for user: {st.session_state.user_id}") # Logging
    if not db or not st.session_state.user_id:
        st.warning("Cannot save: Firebase not initialized or user ID not available.")
        print("Save failed: DB not initialized or User ID missing.") # Logging
        return False
    try:
        # Defines the document path for the current user's session
        doc_ref = db.collection('artifacts').document(APP_ID).collection('users').document(st.session_state.user_id).collection('stories').document('current_session_data')
        
        # Prepare data to save, including chat history and current AI settings
        session_data = {
            "history": st.session_state.story_history, # Firestore can directly store lists of maps
            "current_mode": st.session_state.current_mode,
            "temperature": st.session_state.temperature,
            "tone": st.session_state.tone,
            "timestamp": firestore.SERVER_TIMESTAMP # Records the time of save on the server
        }
        
        # Set the document, merging new data with existing data if the document already exists
        doc_ref.set(session_data, merge=True)
        st.success("Current session saved successfully to cloud! You can resume from here.")
        print(f"Session saved successfully for user: {st.session_state.user_id}") # Logging
        return True
    except Exception as e:
        st.error(f"Error saving session: {e}")
        print(f"Save session error: {e}") # Logging
        return False

def load_story_from_firestore():
    """
    Loads the story history and AI settings for the current user ID from Firestore.
    """
    print(f"Attempting to load session for user: {st.session_state.user_id}") # Logging
    if not db or not st.session_state.user_id:
        st.warning("Cannot load: Firebase not initialized or user ID not available.")
        print("Load failed: DB not initialized or User ID missing.") # Logging
        return False
    try:
        doc_ref = db.collection('artifacts').document(APP_ID).collection('users').document(st.session_state.user_id).collection('stories').document('current_session_data')
        doc = doc_ref.get() # Retrieve the document
        
        if doc.exists:
            data = doc.to_dict() # Convert document to Python dictionary
            # Restore the session state from loaded data, providing defaults if keys are missing
            st.session_state.story_history = data.get("history", [])
            st.session_state.current_mode = data.get("current_mode", 'censored')
            st.session_state.temperature = data.get("temperature", 0.7)
            st.session_state.tone = data.get("tone", "Fantasy")
            st.success("Session loaded successfully from cloud!")
            print(f"Session loaded successfully for user: {st.session_state.user_id}") # Logging
            return True
        else:
            st.info("No saved session found for this user ID.")
            print(f"No saved session found for user: {st.session_state.user_id}") # Logging
            return False
    except Exception as e:
        st.error(f"Error loading session: {e}")
        print(f"Load session error: {e}") # Logging
        return False

# --- Streamlit UI Layout ---

st.set_page_config(
    page_title="Dungeon GPT Lite",
    layout="wide", # Uses the full width of the browser
    initial_sidebar_state="expanded" # Sidebar expanded by default
)

st.title("Dungeon GPT Lite 🎲")

# --- Sidebar for User ID and Debug Info ---
with st.sidebar:
    st.header("Session Info")
    st.write(f"**Your User ID:** `{st.session_state.user_id}`")
    st.caption("This ID links to your saved sessions. It's unique to your browser session. Clearing cache will generate a new ID.")
    st.markdown("---")
    st.header("API Status")
    if GOOGLE_API_KEY:
        if gemini_model_censored and gemini_model_uncensored:
            st.write("✅ Gemini API: All modes configured")
        else:
            st.write("⚠️ Gemini API: Partial configuration. Check key/permissions.")
    else:
        st.write("❌ Gemini API: Not configured. Add GOOGLE_API_KEY.")

# --- Top Buttons for Story Management ---
col_new, col_save, col_load, col_export, col_import = st.columns(5)

with col_new:
    if st.button("New Story", use_container_width=True):
        st.session_state.story_history = [] # Clear history
        st.session_state.current_mode = 'censored' # Reset to default
        st.session_state.temperature = 0.7 # Reset to default
        st.session_state.tone = "Fantasy" # Reset to default
        st.toast("Started a fresh new adventure!")
        print("New story button clicked. Session state reset.") # Logging
        st.rerun() # Force Streamlit to re-render the app with cleared state

with col_save:
    if st.button("Save Session", use_container_width=True):
        save_story_to_firestore()

with col_load:
    if st.button("Load Session", use_container_width=True):
        if load_story_from_firestore():
            st.rerun() # Force Streamlit to re-render with loaded data

with col_export:
    # Export functionality: Create a downloadable JSON file with history and settings
    if st.session_state.story_history:
        # Prepare data structure for export (history + current settings)
        export_data = {
            "history": st.session_state.story_history,
            "settings": {
                "current_mode": st.session_state.current_mode,
                "temperature": st.session_state.temperature,
                "tone": st.session_state.tone
            },
            "exported_from_user_id": st.session_state.user_id # Include user ID for context
        }
        json_for_export = json.dumps(export_data, indent=2) # Pretty-print JSON
        st.download_button(
            label="Export Story (JSON)",
            data=json_for_export,
            file_name=f"dungeon_gpt_story_{st.session_state.user_id[:8]}.json", # File name includes truncated user ID
            mime="application/json", # Set MIME type for JSON files
            use_container_width=True
        )
    else:
        st.button("Export Story (JSON)", disabled=True, use_container_width=True) # Disable button if no history

with col_import:
    # --- IMPORTANT: BEGIN FIX FOR FILE UPLOADER RESET ISSUE ---
    # Wrap the file_uploader and its processing logic in an st.form
    # The clear_on_submit=True argument for st.form will automatically reset
    # all widgets within the form when the form is submitted.
    with st.form(key="import_form", clear_on_submit=True):
        uploaded_file = st.file_uploader(
            "Import Story (JSON)", 
            type="json", # Only allow JSON files
            key="file_uploader_inside_form", # Use a new, unique key for the uploader inside the form
            help="Upload a .json file (exported from Dungeon GPT Lite) to import a story history and settings.", 
            accept_multiple_files=False
        )
        submit_button = st.form_submit_button(label="Process Import")

        if submit_button and uploaded_file is not None:
            print(f"File uploaded: {uploaded_file.name}, size: {uploaded_file.size} bytes") # Logging
            try:
                file_content = uploaded_file.read().decode("utf-8")
                imported_data = json.loads(file_content) # Parse the JSON content

                # Validate expected JSON structure
                if "history" in imported_data and "settings" in imported_data:
                    st.session_state.story_history = imported_data["history"]
                    # Safely update settings, falling back to current state if keys are missing in JSON
                    st.session_state.current_mode = imported_data["settings"].get("current_mode", st.session_state.current_mode)
                    st.session_state.temperature = imported_data["settings"].get("temperature", st.session_state.temperature)
                    st.session_state.tone = imported_data["settings"].get("tone", st.session_state.tone)
                    st.success("Story and settings imported successfully!")
                    print("Story and settings imported successfully.") # Logging
                else:
                    st.error("Invalid JSON format. Please upload a file with 'history' and 'settings' keys.")
                    print("Import failed: Invalid JSON format.") # Logging
                
                # The file_uploader inside the form will be cleared automatically by clear_on_submit=True
                # We still need a rerun to update the main chat display and settings outside the form.
                st.rerun() 
            except json.JSONDecodeError:
                st.error("Invalid JSON file. Please upload a valid JSON file.")
                print("Import failed: JSONDecodeError - Invalid JSON file.") # Logging
            except Exception as e:
                # Catching generic Exception here for broader error logging
                st.error(f"Error importing story: {e}")
                print(f"Import failed with unexpected error: {e}") # Logging
    # --- IMPORTANT: END FIX FOR FILE UPLOADER RESET ISSUE ---


st.markdown("---") # Visual separator

# --- AI Settings Section ---
st.subheader("AI Settings")
settings_col1, settings_col2, settings_col3 = st.columns(3)

with settings_col1:
    st.session_state.current_mode = st.selectbox(
        "Response Mode",
        options=['censored', 'uncensored'],
        index=0 if st.session_state.current_mode == 'censored' else 1,
        help="Choose between standard Gemini (Censored) or a less-filtered Gemini setting (Uncensored).",
        key="mode_selector" # Unique key to prevent widget identity issues
    )

with settings_col2:
    st.session_state.temperature = st.slider(
        "Temperature",
        min_value=0.0,
        max_value=1.0,
        value=st.session_state.temperature,
        step=0.05,
        help="Controls creativity vs. predictability (0.0=predictable, 1.0=creative).",
        key="temp_slider" # Unique key
    )

with settings_col3:
    st.session_state.tone = st.selectbox(
        "Story Tone/Genre",
        options=["Fantasy", "Sci-Fi", "Horror", "Mystery", "Comedy", "Historical"],
        index=["Fantasy", "Sci-Fi", "Horror", "Mystery", "Comedy", "Historical"].index(st.session_state.tone),
        help="Set the desired genre or tone for the AI's responses.",
        key="tone_selector" # Unique key
    )

# Display current settings for user clarity
st.info(f"Current AI Mode: **{st.session_state.current_mode.capitalize()}** | Temperature: **{st.session_state.temperature}** | Tone: **{st.session_state.tone}**")

st.markdown("---") # Visual separator

# --- Chat Display Area ---
# This container will display all messages in the story history
chat_display_container = st.container()
with chat_display_container:
    for message in st.session_state.story_history:
        # Use Streamlit's built-in chat message styling for user and AI
        with st.chat_message(message["sender"]): 
            st.write(message["text"])

# --- User Input at the Bottom ---
user_prompt = st.chat_input("Type your action or prompt here...", key="chat_input")

if user_prompt:
    # Add the user's new message to the story history
    st.session_state.story_history.append({"sender": "user", "text": user_prompt})
    print(f"User prompt received: {user_prompt}") # Logging

    # Prepare the full context for the AI, including tone/genre and recent history
    # The system prompt is prepended to guide the AI's role and tone
    full_context = (
        f"You are an AI Dungeon Master. "
        f"The story's tone is: {st.session_state.tone}. "
        "Generate the next part of the fantasy story based on the following conversation:\n\n"
    )
    
    # Append a limited number of recent messages to the context to manage token usage
    # Sending too much history can lead to API errors or increased costs.
    # Adjust [-10:] to change how many previous turns are sent as context.
    for msg in st.session_state.story_history[-10:]:
        full_context += f"{msg['sender'].upper()}: {msg['text']}\n"
    full_context += "AI:" # Explicitly tell the AI it's its turn to respond

    with st.spinner("Generating AI response..."): # Show a loading spinner while AI processes
        ai_response_text = generate_gemini_response(
            full_context, 
            st.session_state.temperature, 
            st.session_state.current_mode
        )
        
        # Add the AI's response to the story history
        st.session_state.story_history.append({"sender": "ai", "text": ai_response_text})
        print(f"AI response added to history (first 200 chars): {ai_response_text[:200]}...") # Logging

    st.rerun() # Force Streamlit to re-execute the script and update the chat display

# --- Initial Welcome Message ---
# Display a welcome message only when the app first loads or a new story is started
if not st.session_state.story_history:
    st.session_state.story_history.append({"sender": "ai", "text": "Welcome, adventurer! What quest shall we embark on today?"})
    print("Initial welcome message displayed.") # Logging
    st.rerun() # Rerun to ensure the welcome message is displayed immediately
