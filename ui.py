import streamlit as st
import pymupdf  # PyMuPDF
from linkedin_api.linkedin import Linkedin
import google.generativeai as genai
import os
from dotenv import load_dotenv

# --- Load .env file ---
load_dotenv()

# --- Helper functions (unchanged except minor tweaks) ---

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
            item_str = f"{key}: "
            if isinstance(value, dict) and 'text' in value:
                item_str += value.get('text', 'N/A')
            elif isinstance(value, list):
                try:
                    item_str += ", ".join(str(s.get('name', s)) if isinstance(s, dict) else str(s) for s in value)
                except:
                    item_str += str(value)
            else:
                item_str += str(value)
            linkedin_items_str.append(item_str[:500])
        formatted_str = "\n".join(linkedin_items_str)
        return formatted_str if formatted_str else "No specific LinkedIn data items were formatted."
    return "LinkedIn data is in an unexpected format."


def summarise_linkedin_and_cv(cv_data: str, linkedin_profile_data: list | str, gemini_api_key: str) -> str:
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
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Gemini API Error (Summarizer): {e}"


def get_interview_response(summary_context: str, chat_history: list, user_input: str, gemini_api_key: str) -> str:
    try:
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel('gemini-1.5-flash-latest')

        system_prompt = f"""You are a friendly and professional AI interviewer.
Your goal is to conduct an initial screening interview with the candidate.
You have the following summary of the candidate's profile:
--- CANDIDATE SUMMARY START ---
{summary_context}
--- CANDIDATE SUMMARY END ---

Conduct the interview with a warm, encouraging tone, asking relevant questions, and providing helpful feedback.
"""

        full_prompt_history = [{'role': 'system', 'content': system_prompt}]

        for message in chat_history:
            full_prompt_history.append({'role': message["role"], 'content': message["content"]})

        full_prompt_history.append({'role': 'user', 'content': user_input})

        chat_session = model.start_chat(history=full_prompt_history[:-1])
        response = chat_session.send_message(full_prompt_history[-1]['content'])

        return response.text

    except Exception as e:
        return f"Gemini API Error (Chatbot): {e}"


# --- Streamlit UI & Onboarding flow ---

st.title("🎙️ Charisma AI Interviewer Bot")

# Initialize session state variables for onboarding and chat
if 'onboarding_step' not in st.session_state:
    st.session_state.onboarding_step = 0
if 'onboarding_answers' not in st.session_state:
    st.session_state.onboarding_answers = {}
if 'interview_ready' not in st.session_state:
    st.session_state.interview_ready = False
if 'summary_for_interview' not in st.session_state:
    st.session_state.summary_for_interview = ""
if 'chat_messages' not in st.session_state:
    st.session_state.chat_messages = []
if 'gemini_api_key' not in st.session_state:
    st.session_state.gemini_api_key = ""

# Sidebar inputs for optional LinkedIn and CV upload + Gemini key
st.sidebar.header("🔑 Credentials & Profile Options")
default_linkedin_email = os.environ.get("LINKEDIN_EMAIL", "")
default_linkedin_password = os.environ.get("LINKEDIN_PASSWORD", "")
default_gemini_key = os.environ.get("GEMINI_API_KEY", "")

linkedin_email = st.sidebar.text_input("LinkedIn Email (if using LinkedIn scraping)", value=default_linkedin_email)
linkedin_password = st.sidebar.text_input("LinkedIn Password", type="password", value=default_linkedin_password)
gemini_key_input = st.sidebar.text_input("Gemini API Key", type="password", value=default_gemini_key)
uploaded_cv = st.sidebar.file_uploader("Upload CV (PDF)", type="pdf")
linkedin_url = st.sidebar.text_input("LinkedIn Profile URL (optional)")

if gemini_key_input:
    st.session_state.gemini_api_key = gemini_key_input

# Define onboarding questions per your flow
onboarding_questions = [
    "What’s your current role, and how long have you been doing it? (Or upload a resume/LinkedIn link above)",
    "What’s got you preparing for interviews right now? (Layoff, promotion, dream company, etc.)",
    "Where are you in your interview process? (Just starting, interviewing, final rounds, practicing, etc.)",
    "Any particular role or company you have your eye on? (Type or upload a job description if you want)",
    "If we fast-forward a few weeks, what do you wish felt easier? (Confidence, clarity, nerves, etc.)"
]

def onboarding_flow():
    step = st.session_state.onboarding_step
    st.markdown(
        "Hey — welcome! 😊\n\n"
        "Before we dive into practice, I want to understand a bit about you — just a few questions, and then we’ll jump in."
    )
    st.markdown(f"**Question {step + 1}:** {onboarding_questions[step]}")

    # Show previous answer if exists
    default_val = st.session_state.onboarding_answers.get(step, "")

    user_answer = st.text_area("Your answer:", value=default_val, key=f"answer_{step}", height=100)

    col1, col2 = st.columns([1,1])
    with col1:
        if st.button("⬅️ Back", disabled=(step == 0)):
            st.session_state.onboarding_step = max(step - 1, 0)
            st.experimental_rerun()
    with col2:
        if st.button("Next ➡️"):
            if not user_answer.strip():
                st.warning("Please enter your answer before continuing.")
            else:
                st.session_state.onboarding_answers[step] = user_answer.strip()
                if step + 1 < len(onboarding_questions):
                    st.session_state.onboarding_step += 1
                    st.experimental_rerun()
                else:
                    st.session_state.interview_ready = True
                    st.experimental_rerun()

# Main app logic

if not st.session_state.interview_ready:
    onboarding_flow()
else:
    st.success("Thanks for sharing! Generating your professional summary now...")

    # Combine onboarding answers into one text block for summary generation
    combined_onboarding_text = "\n".join(
        f"{onboarding_questions[i]}: {st.session_state.onboarding_answers.get(i, '')}"
        for i in range(len(onboarding_questions))
    )

    # Prepare CV text (if uploaded)
    cv_text = None
    if uploaded_cv:
        cv_text = extract_text_from_cv(uploaded_cv)
        if "Error reading PDF:" in cv_text:
            st.error(cv_text)
            cv_text = None

    # Prepare LinkedIn data (if URL + credentials provided)
    linkedin_data = None
    if linkedin_url and linkedin_email and linkedin_password:
        with st.spinner("Fetching LinkedIn profile data..."):
            linkedin_data = linkedin_scrapper(linkedin_email, linkedin_password, linkedin_url)
        if isinstance(linkedin_data, str) and linkedin_data.startswith("Error"):
            st.error(f"LinkedIn Error: {linkedin_data}")
            linkedin_data = None

    # Generate or reuse summary
    if not st.session_state.summary_for_interview:
        with st.spinner("Calling Gemini to generate summary..."):
            summary_result = summarise_linkedin_and_cv(
                cv_data=cv_text if cv_text else combined_onboarding_text,
                linkedin_profile_data=linkedin_data if linkedin_data else "No LinkedIn data provided.",
                gemini_api_key=st.session_state.gemini_api_key,
            )
            if "Gemini API Error" in summary_result:
                st.error(summary_result)
            else:
                st.session_state.summary_for_interview = summary_result
                st.success("Professional summary generated! Let's start the interview.")
                st.experimental_rerun()

    # Display summary context
    if st.session_state.summary_for_interview:
        st.subheader("📝 Your Profile Summary (Context for Interviewer)")
        st.markdown(st.session_state.summary_for_interview)
        st.markdown("---")

    # Interview chat interface
    st.subheader("🎤 AI Interviewer Chat")

    # Show chat messages
    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input
    if prompt := st.chat_input("Your response..."):
        st.session_state.chat_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            placeholder = st.empty()
            placeholder.markdown("Thinking...")

            # Prepare chat history excluding latest user message
            api_chat_history = st.session_state.chat_messages[:-1]

            response = get_interview_response(
                summary_context=st.session_state.summary_for_interview,
                chat_history=api_chat_history,
                user_input=prompt,
                gemini_api_key=st.session_state.gemini_api_key,
            )
            placeholder.markdown(response)
            st.session_state.chat_messages.append({"role": "assistant", "content": response})
