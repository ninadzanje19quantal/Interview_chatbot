import streamlit as st
import pymupdf  # PyMuPDF
from linkedin_api.linkedin import Linkedin
import google.generativeai as genai
import os
from dotenv import load_dotenv

# --- Load .env file for local development ---
load_dotenv()


# --- Your Original Helper Functions (with minimal necessary changes from previous version) ---

def linkedin_scrapper(user_email: str, user_password: str, profile_url: str) -> list | str:
    temp = []
    try:
        api = Linkedin(user_email, user_password, refresh_cookies=False)
    except Exception as e:
        return f"Incorrect Credentials or LinkedIn API issue: {e}"

    try:
        if "/in/" in profile_url:
            user_profile_id = profile_url.split("/in/")[1].split("/")[0].split("?")[0]
        else:
            user_profile_id = profile_url.split(r"/")[-1].split("?")[0]

        if not user_profile_id:
            return "Could not extract a valid profile ID from the URL."

        profile_data = api.get_profile(user_profile_id)
    except Exception as e:
        return f"Error fetching profile (ID: {user_profile_id if 'user_profile_id' in locals() else 'unknown'}): {e}"

    if not profile_data:
        return "Profile does not exist or could not be fetched (empty response)."

    profile_data_items = list(profile_data.items())

    if len(profile_data_items) == 0:
        return "Profile data is empty after fetching."

    try:
        # These indices are fragile examples.
        temp.append(profile_data_items[0])
        if len(profile_data_items) > 16: temp.append(profile_data_items[16])
        if len(profile_data_items) > 34: temp.append(profile_data_items[34])
        if len(profile_data_items) > 30: temp.append(profile_data_items[30])
    except IndexError:
        return f"Error accessing profile data by index. API response structure may have changed. Data items count: {len(profile_data_items)}"

    if not temp:
        return "No specific data points could be extracted by index."
    return temp


def extract_text_from_cv(uploaded_file) -> str | None:
    try:
        doc = pymupdf.open(stream=uploaded_file.read(), filetype="pdf")
        full_text = [page.get_text("text") for page in doc]
        doc.close()
        return "\n".join(full_text)
    except Exception as e:
        return f"Error reading PDF: {e}"


def format_linkedin_data_for_prompt(linkedin_profile_data: list | str) -> str:
    if isinstance(linkedin_profile_data, str):
        return f"LinkedIn data not available: {linkedin_profile_data}"
    elif isinstance(linkedin_profile_data, list):
        linkedin_items_str = []
        for key, value in linkedin_profile_data:
            # Basic formatting for the list of tuples
            item_str = f"{key}: "
            if isinstance(value, dict) and 'text' in value:
                item_str += value.get('text', 'N/A')
            elif isinstance(value, list):
                # Simple join for list items (e.g., skills)
                try:
                    item_str += ", ".join(str(s.get('name', s)) if isinstance(s, dict) else str(s) for s in value)
                except:  # Fallback for unexpected list content
                    item_str += str(value)
            else:
                item_str += str(value)
            linkedin_items_str.append(item_str[:500])  # Truncate long values
        formatted_str = "\n".join(linkedin_items_str)
        return formatted_str if formatted_str else "No specific LinkedIn data items were formatted."
    return "LinkedIn data is in an unexpected format."


def summarise_linkedin_and_cv(
        cv_data: str,
        linkedin_profile_data: list | str,  # Output from your linkedin_scrapper
        gemini_api_key: str
) -> str:
    cv_text_for_prompt = cv_data if cv_data and "Error reading PDF:" not in cv_data else "CV data not available or error during extraction."
    linkedin_text_for_prompt = format_linkedin_data_for_prompt(linkedin_profile_data)

    prompt = f"""
    Please provide a concise professional summary based on the following data.
    Highlight key skills, experiences, and overall professional profile.

    CV Data:
    ---
    {cv_text_for_prompt}
    ---

    LinkedIn Data:
    ---
    {linkedin_text_for_prompt}
    ---

    Begin the summary:
    """
    try:
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel('gemini-1.5-flash-latest')  # Or 'gemini-pro'
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Gemini API Error (Summarizer): {e}"


def get_interview_response(
        summary_context: str,
        chat_history: list,  # List of {"role": "user/model", "content": "..."}
        user_input: str,
        gemini_api_key: str
) -> str:
    try:
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel('gemini-1.5-flash-latest')  # Or 'gemini-pro'

        # Construct the messages for the chat model
        # The system prompt is implicitly part of the first user message structure for some models,
        # or can be explicitly set if the API supports a system role.
        # For Gemini, we build a history.

        # Start with the system instruction and summary
        # For Gemini, it's often better to include system instructions as part of the conversational turn.
        # We'll prepend it to the history that Gemini sees.

        system_prompt = f"""You are a friendly and professional AI interviewer.
Your goal is to conduct an initial screening interview with the candidate.
You have the following summary of the candidate's CV and LinkedIn profile:
--- CANDIDATE SUMMARY START ---
{summary_context}
--- CANDIDATE SUMMARY END ---

Your previous conversation history with the candidate is:
"""
        # We will send the history as a list of `Content` objects (parts)
        # For this, we convert our simple chat_history to the expected format if needed

        full_prompt_history = []

        # Initial instruction for the model (can be seen as a system-like prompt)
        full_prompt_history.append({'role': 'user', 'parts': [
            system_prompt + "Let's begin the interview. Please ask your first question, or respond to my previous statement."]})
        full_prompt_history.append({'role': 'model', 'parts': [
            "Okay, I understand. Based on your summary, let's start. Could you tell me a bit more about your experience with [mention a skill or experience from summary]?"]})  # Example initial bot turn

        # Add actual chat history
        for message in chat_history:
            full_prompt_history.append({'role': message["role"], 'parts': [message["content"]]})

        # Add the latest user input
        full_prompt_history.append({'role': 'user', 'parts': [user_input]})

        chat_session = model.start_chat(history=full_prompt_history[:-1])  # History up to the last user message
        response = chat_session.send_message(full_prompt_history[-1]['parts'][0])  # Send the last user message

        return response.text

    except Exception as e:
        return f"Gemini API Error (Chatbot): {e}"


# --- Streamlit UI ---
st.title("AI Interviewer Bot")

# --- Initialize session state ---
if 'summary' not in st.session_state:
    st.session_state.summary = ""
if 'cv_processed' not in st.session_state:  # To track if CV was processed
    st.session_state.cv_processed = False
if 'linkedin_processed' not in st.session_state:  # To track if LinkedIn was processed
    st.session_state.linkedin_processed = False
if "chat_messages" not in st.session_state:  # For chatbot
    st.session_state.chat_messages = []
if "summary_for_interview" not in st.session_state:  # Store the clean summary for chatbot
    st.session_state.summary_for_interview = ""

# --- Sidebar for Inputs ---
st.sidebar.header("🔑 Credentials & Profile")
default_linkedin_email = os.environ.get("LINKEDIN_EMAIL", "")
default_linkedin_password = os.environ.get("LINKEDIN_PASSWORD", "")
default_gemini_key = os.environ.get("GEMINI_API_KEY", "")

user_email_input = st.sidebar.text_input("LinkedIn Email", value=default_linkedin_email, key="li_email")
user_password_input = st.sidebar.text_input("LinkedIn Password", type="password", value=default_linkedin_password,
                                            key="li_pass")
gemini_api_key_input = st.sidebar.text_input("Gemini API Key", type="password", value=default_gemini_key, key="gem_key")

st.sidebar.header("📄 Inputs")
uploaded_cv_file = st.sidebar.file_uploader("Upload CV (PDF)", type="pdf", key="cv_upload")
linkedin_url_input = st.sidebar.text_input("LinkedIn Profile URL", key="li_url")

if st.sidebar.button("🚀 Process Profile & Start Interview Prep", key="process_button"):
    st.session_state.summary = ""  # Clear previous summary
    st.session_state.summary_for_interview = ""
    st.session_state.chat_messages = []  # Reset chat
    st.session_state.cv_processed = False
    st.session_state.linkedin_processed = False
    error_messages = []

    # Validate inputs
    if not gemini_api_key_input:
        st.sidebar.error("Gemini API Key is required.")
    elif not uploaded_cv_file and not linkedin_url_input:
        st.sidebar.error("Please upload a CV or provide a LinkedIn URL (or both).")
    elif linkedin_url_input and (not user_email_input or not user_password_input):
        st.sidebar.error("LinkedIn credentials are required if providing a LinkedIn URL.")
    else:
        cv_data_text = None
        linkedin_profile_info = None

        with st.spinner("Processing profile data..."):
            # 1. Extract text from CV
            if uploaded_cv_file:
                cv_data_text = extract_text_from_cv(uploaded_cv_file)
                st.session_state.cv_processed = True
                if "Error reading PDF:" in cv_data_text:
                    error_messages.append(f"CV Error: {cv_data_text}")
                    cv_data_text = None  # Nullify on error for summary

            # 2. Scrape LinkedIn profile
            if linkedin_url_input:
                linkedin_profile_info = linkedin_scrapper(user_email_input, user_password_input, linkedin_url_input)
                st.session_state.linkedin_processed = True
                if isinstance(linkedin_profile_info, str):  # Error from scrapper
                    error_messages.append(f"LinkedIn Error: {linkedin_profile_info}")
                    linkedin_profile_info = None  # Nullify on error for summary

            # 3. Generate Summary if any data was processed
            if cv_data_text or linkedin_profile_info:
                summary_result = summarise_linkedin_and_cv(
                    cv_data=cv_data_text if cv_data_text else "No CV data processed.",
                    linkedin_profile_data=linkedin_profile_info if linkedin_profile_info else "No LinkedIn data processed.",
                    gemini_api_key=gemini_api_key_input
                )
                st.session_state.summary = summary_result
                if "Gemini API Error" not in summary_result:
                    st.session_state.summary_for_interview = summary_result  # Store for chatbot
                else:
                    error_messages.append(summary_result)  # Add Gemini error to display
            elif not st.session_state.cv_processed and not st.session_state.linkedin_processed:
                st.session_state.summary = "No data (CV or LinkedIn) was provided for processing."

            if error_messages:
                for err in error_messages:
                    st.error(err)
            elif st.session_state.summary_for_interview:
                st.success("Profile summary generated! The interview bot is ready below.")
            elif not st.session_state.summary:  # If no summary and no specific errors, means no data
                st.warning("No data was available to generate a summary.")

# --- Display Summary (Optional, but good for user to see context) ---
if st.session_state.summary:
    st.subheader("📝 Your Profile Summary (Context for Interviewer)")
    if "Error" in st.session_state.summary:
        st.error(st.session_state.summary)
    else:
        st.markdown(st.session_state.summary)
    st.markdown("---")

# --- Interview Chatbot Section ---
if st.session_state.summary_for_interview and "Gemini API Error" not in st.session_state.summary_for_interview:
    st.subheader("🎙️ AI Interviewer")

    # Display existing chat messages
    for message in st.session_state.chat_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Chat input
    if prompt := st.chat_input("Your response..."):
        st.session_state.chat_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            message_placeholder.markdown("Thinking...")

            # Prepare chat history for the API
            api_chat_history = []
            for msg in st.session_state.chat_messages[:-1]:  # Exclude the latest user message for history
                api_chat_history.append({"role": msg["role"], "content": msg["content"]})

            assistant_response = get_interview_response(
                summary_context=st.session_state.summary_for_interview,
                chat_history=api_chat_history,  # Pass history up to previous turn
                user_input=prompt,  # Pass current user input
                gemini_api_key=gemini_api_key_input
            )
            message_placeholder.markdown(assistant_response)
        st.session_state.chat_messages.append({"role": "assistant", "content": assistant_response})
        # No st.rerun() needed here, chat_input and message display handle updates.

elif st.session_state.cv_processed or st.session_state.linkedin_processed:  # If processing was attempted
    if not st.session_state.summary_for_interview and st.session_state.summary and "Error" in st.session_state.summary:
        st.warning("Could not prepare for interview due to errors in summary generation.")
    elif not st.session_state.summary_for_interview:
        st.info("Click 'Process Profile & Start Interview Prep' to begin.")
else:
    st.info("Upload your CV and/or LinkedIn profile, then click 'Process Profile & Start Interview Prep' to begin.")
