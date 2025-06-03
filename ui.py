import streamlit as st
import google.generativeai as genai
from linkedin_api import Linkedin  # For Linkedin Scraper
import pymupdf  # For PDF parsing (fitz)
import re  # For cleaning up LinkedIn profile ID


# --- LinkedIn Scraper Function (modified slightly for clarity) ---
def convert_linkedin_url_to_id(profile_url: str) -> str:
    """
    Extracts the public profile ID from a LinkedIn URL.
    Handles common URL formats like:
    - https://www.linkedin.com/in/username/
    - https://www.linkedin.com/in/username
    - www.linkedin.com/in/username
    """
    if not profile_url:
        return ""
    # Remove protocol and www if present
    profile_url = re.sub(r"^(https?://)?(www\.)?linkedin\.com/in/", "", profile_url)
    # Remove trailing slash if present
    if profile_url.endswith('/'):
        profile_url = profile_url[:-1]
    return profile_url


def linkedin_scrapper(user_email: str, user_password: str, profile_url: str) -> tuple[str, list | str]:
    """
    Scrapes LinkedIn profile data.
    Returns a tuple: (status_message, data_or_error_string)
    """
    temp = []
    api = None  # Initialize api to None
    try:
        st.write("Attempting to log in to LinkedIn...")
        api = Linkedin(user_email, user_password, refresh_cookies=True)  # Added refresh_cookies
        st.write("LinkedIn login successful.")
    except Exception as e:
        st.error(f"LinkedIn Login Error: {e}")
        return "Incorrect Credentials or Login Issue", f"Error: {e}"

    if not api:  # Check if api object was successfully created
        return "LinkedIn API not initialized", "Error: API object is None."

    try:
        user_profile_id = convert_linkedin_url_to_id(profile_url)
        if not user_profile_id:
            return "Invalid Profile URL", "Error: Could not extract profile ID from URL."

        st.write(f"Fetching profile for ID: {user_profile_id}...")
        profile_data = api.get_profile(user_profile_id)  # Use the extracted ID

        if not profile_data:  # Check if profile_data is None or empty
            return "Profile does not exist or is private", "Error: No data returned for profile."

        # It's safer to check if keys exist before accessing
        # And to convert items to a list of tuples only if it's a dict
        if isinstance(profile_data, dict):
            profile_items = list(profile_data.items())  # This was the original intent
        else:
            st.warning("Profile data is not in the expected dictionary format. Raw data:")
            st.json(profile_data)  # Show what was received
            return "Unexpected Profile Data Format", "Error: Profile data is not a dictionary."

        # The original indexing is very fragile.
        # It assumes a fixed order and length of profile_items.
        # A better approach would be to get items by their actual keys.
        # For example: profile_data.get('headline'), profile_data.get('summary')
        # However, sticking to the provided logic for now:

        # Safety checks for indices
        data_map = {
            "headline": profile_data.get('headline', 'N/A'),
            "summary": profile_data.get('summary', 'N/A'),  # 'summary' is more common than 'about'
            "skills": [skill.get('name', 'N/A') for skill in profile_data.get('skills', [])],
            # Skills are usually a list of dicts
            "certifications": profile_data.get('certifications', []),  # Assuming this key exists
            # "experiences": profile_data.get('experience', []), # Example for experiences
            # "education": profile_data.get('education', [])   # Example for education
        }
        # Let's try to get the requested data using dictionary keys where possible
        temp.append(("headline", data_map["headline"]))
        temp.append(("summary", data_map["summary"]))  # 'about' might be 'summary'
        temp.append(("skills", data_map["skills"]))
        temp.append(("certifications", data_map["certifications"]))

        # Fallback to original indexing if direct key access fails or for very specific items
        # This section is very risky and likely to break.
        # It assumes the original structure based on list(profile_data.items())
        # Example: if you knew headline was always the first item:
        # if len(profile_items) > 0: temp.append(profile_items[0]) # headline
        # if len(profile_items) > 16: temp.append(profile_items[16]) # about (highly unlikely to be stable)
        # if len(profile_items) > 34: temp.append(profile_items[34]) # skills
        # if len(profile_items) > 30: temp.append(profile_items[30]) # certifications

        st.write("LinkedIn data fetched successfully.")
        return "Success", temp

    except Exception as e:
        st.error(f"Error fetching LinkedIn profile data: {e}")
        return "Scraping Error", f"Error: {e}"


# --- CV Text Extraction Function ---
def extract_text_from_cv(uploaded_file) -> str | None:
    if uploaded_file is None:
        return None
    try:
        # Read uploaded file as BytesIO
        doc = pymupdf.open(stream=uploaded_file.read(), filetype="pdf")
        full_text = []
        for page_num in range(doc.page_count):
            page = doc.load_page(page_num)
            page_text = page.get_text("text")
            full_text.append(page_text)
        doc.close()
        return "\n".join(full_text)
    except Exception as e:
        st.error(f"Error reading PDF: {e}")
        return f"Error reading PDF: {e}"


# --- Combined Summary Function (Modified) ---
def summarise_linkedin_and_cv(api_key_gemini: str, cv_text: str | None, linkedin_data_str: str | None) -> str:
    if not api_key_gemini:
        return "Error: Gemini API key not provided."

    try:
        genai.configure(api_key=api_key_gemini)
        model = genai.GenerativeModel('gemini-1.5-flash-latest')  # Or 'gemini-pro'
    except Exception as e:
        return f"Error configuring Gemini: {e}"

    prompt_parts = ["Please provide a concise summary of the candidate based on the following information."]
    if cv_text and cv_text.strip():
        prompt_parts.append(f"\n\n--- CV Data ---\n{cv_text}")
    if linkedin_data_str and linkedin_data_str.strip() and linkedin_data_str != "Error":  # Check if it's not an error message
        prompt_parts.append(f"\n\n--- LinkedIn Data ---\n{linkedin_data_str}")

    if len(prompt_parts) == 1:  # Only the initial instruction, no data
        return "No CV or LinkedIn data provided to summarize."

    prompt = "".join(prompt_parts)

    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Error generating summary with Gemini: {e}"


# --- Initial Interview Questions ---
INITIAL_QUESTIONS_TEXT = """
Hey, welcome — I’m really glad you’re here.
Before we dive into practice, I want to understand a bit about you — where you’re coming from, what you’re aiming for, and how I can be most helpful.
Just a few questions, and then we’ll jump in.

Let’s start with your work — just so I get a sense of the world you operate in.
1. What’s your current role, and how long have you been doing it?
If it’s easier, feel free to link your LinkedIn or drop a resume — totally up to you. (This app already asks for these)

2. What’s got you preparing for interviews right now?
 You don’t need a perfect answer — just what’s true for you.
Some folks are job hunting after a layoff. Others are aiming for a big move — a promotion, a better offer, a dream company. And some just want to get better at telling their story.
Which of those feels most like your situation?

3. Just so I know how fast to go — where are you in your interview process?
 Still early? Already in the loop? Just sharpening up?
No pressure either way. This just helps me meet you where you are.

4. Any particular role or company you’ve got your eye on?
 You can type something like “PM at Google” or “Marketing lead at a Series A startup.”
 Or upload a job description if you’ve got one handy. (JD upload not implemented in this version)
And if you're still figuring it out, that’s totally fine — we can start general and narrow in as you go.

5. If we could fast-forward a few weeks — what do you wish felt easier?
 Not just knowing the answers, but how you say them.
A few things I help with — let me know what clicks:
Making answers clearer and more structured
Sounding more confident, less hesitant
Getting to the point without rambling
Speaking with polish and presence
Managing nerves when it counts
Cutting the filler words
Actually being memorable — in a good way
Pick what matters to you — we’ll build from there.
"""

# --- Streamlit App ---
st.set_page_config(layout="wide", page_title="AI Interview Prep Assistant")

st.title("🤖 AI Interview Prep Assistant")
st.markdown("Get ready for your next interview with AI-powered practice!")

# --- Initialize session state ---
if "gemini_api_key" not in st.session_state:
    st.session_state.gemini_api_key = ""
if "linkedin_email" not in st.session_state:
    st.session_state.linkedin_email = ""
if "linkedin_password" not in st.session_state:
    st.session_state.linkedin_password = ""
if "linkedin_url" not in st.session_state:
    st.session_state.linkedin_url = ""
if "cv_text" not in st.session_state:
    st.session_state.cv_text = None
if "linkedin_data_str" not in st.session_state:
    st.session_state.linkedin_data_str = None
if "initial_answers_str" not in st.session_state:
    st.session_state.initial_answers_str = ""
if "combined_summary" not in st.session_state:
    st.session_state.combined_summary = ""
if "interview_started" not in st.session_state:
    st.session_state.interview_started = False
if "messages" not in st.session_state:  # For chatbot
    st.session_state.messages = []
if "gemini_chat" not in st.session_state:
    st.session_state.gemini_chat = None
if "data_processed" not in st.session_state:
    st.session_state.data_processed = False

# --- Sidebar for Credentials ---
with st.sidebar:
    st.header("🔒 Credentials & Setup")
    st.session_state.gemini_api_key = st.text_input("Gemini API Key", type="password",
                                                    value=st.session_state.gemini_api_key)
    st.session_state.linkedin_email = st.text_input("LinkedIn Email", value=st.session_state.linkedin_email)
    st.session_state.linkedin_password = st.text_input("LinkedIn Password", type="password",
                                                       value=st.session_state.linkedin_password)

    st.markdown("---")
    st.info(
        "Your LinkedIn credentials are used locally to fetch your profile data and are not stored long-term. However, be cautious with entering credentials.")
    st.warning("Automated access to LinkedIn can sometimes lead to account issues. Use responsibly.")

# --- Main App Layout ---
col1, col2 = st.columns(2)

with col1:
    st.subheader("Step 1: Provide Your Information")
    st.session_state.linkedin_url = st.text_input("🔗 Your LinkedIn Profile URL", value=st.session_state.linkedin_url,
                                                  placeholder="https://www.linkedin.com/in/yourname/")
    uploaded_cv = st.file_uploader("📄 Upload Your CV/Resume (PDF only)", type="pdf")

    if uploaded_cv and not st.session_state.cv_text:  # Process if new CV uploaded and not already processed
        with st.spinner("Extracting text from CV..."):
            st.session_state.cv_text = extract_text_from_cv(uploaded_cv)
            if st.session_state.cv_text and "Error reading PDF" not in st.session_state.cv_text:
                st.success("CV text extracted!")
            elif st.session_state.cv_text:
                st.error(st.session_state.cv_text)  # Show the error from extraction
            else:
                st.error("Could not extract text from CV.")

    st.markdown("---")
    st.subheader("Step 2: Answer Initial Questions")
    st.markdown(INITIAL_QUESTIONS_TEXT.split("1.")[0])  # Intro text

    q_prompts = [
        "1. What’s your current role, and how long have you been doing it?",
        "2. What’s got you preparing for interviews right now? (e.g., job hunting, promotion, skill improvement)",
        "3. Where are you in your interview process? (e.g., early, in the loop, sharpening up)",
        "4. Any particular role or company you’ve got your eye on? (e.g., PM at Google, Marketing lead at Series A startup)",
        "5. If we could fast-forward a few weeks — what do you wish felt easier? (e.g., clearer answers, more confident, less rambling, managing nerves)"
    ]

    initial_answers = {}
    if 'initial_answers_dict' not in st.session_state:
        st.session_state.initial_answers_dict = {q: "" for q in q_prompts}

    for i, q_text in enumerate(q_prompts):
        st.session_state.initial_answers_dict[q_text] = st.text_area(
            q_text,
            value=st.session_state.initial_answers_dict.get(q_text, ""),
            height=100,
            key=f"initial_q_{i}"
        )

    if st.button("🚀 Process My Info & Start Interview Prep", disabled=st.session_state.data_processed):
        if not st.session_state.gemini_api_key:
            st.error("Please enter your Gemini API Key in the sidebar.")
        else:
            with st.spinner("Processing your information... This may take a moment."):
                # 1. Get LinkedIn Data
                if st.session_state.linkedin_url and st.session_state.linkedin_email and st.session_state.linkedin_password:
                    st.write("Fetching LinkedIn data...")
                    status_msg, linkedin_result = linkedin_scrapper(
                        st.session_state.linkedin_email,
                        st.session_state.linkedin_password,
                        st.session_state.linkedin_url
                    )
                    if status_msg == "Success":
                        st.session_state.linkedin_data_str = str(linkedin_result)  # Convert list of tuples to string
                        st.success("LinkedIn data fetched.")
                    else:
                        st.error(f"LinkedIn Error: {status_msg} - {linkedin_result}")
                        st.session_state.linkedin_data_str = f"Error fetching LinkedIn data: {linkedin_result}"
                else:
                    st.warning("LinkedIn details not fully provided. Skipping LinkedIn data.")
                    st.session_state.linkedin_data_str = "Not provided."

                # 2. Format initial answers
                answers_list = []
                for q, a in st.session_state.initial_answers_dict.items():
                    if a.strip():  # only include answered questions
                        answers_list.append(f"Q: {q}\nA: {a.strip()}")
                st.session_state.initial_answers_str = "\n\n".join(answers_list)
                if not st.session_state.initial_answers_str:
                    st.session_state.initial_answers_str = "User did not provide answers to initial questions."

                # 3. Create Combined Summary
                st.write("Generating combined summary using Gemini...")
                st.session_state.combined_summary = summarise_linkedin_and_cv(
                    st.session_state.gemini_api_key,
                    st.session_state.cv_text,
                    st.session_state.linkedin_data_str
                )
                if "Error" not in st.session_state.combined_summary:
                    st.success("Summary generated!")
                else:
                    st.error(f"Summary Generation Failed: {st.session_state.combined_summary}")

                # 4. Prepare for chat
                if "Error" not in st.session_state.combined_summary:  # Only proceed if summary is good
                    st.session_state.interview_started = True
                    st.session_state.data_processed = True  # Prevent reprocessing
                    st.session_state.messages = []  # Reset chat history

                    # Initialize Gemini Chat
                    try:
                        genai.configure(api_key=st.session_state.gemini_api_key)
                        model = genai.GenerativeModel('gemini-1.5-flash-latest')  # Or 'gemini-pro'

                        # Construct comprehensive context for the chat model
                        chat_context = f"""
                        You are an expert interview coach. Your goal is to help the candidate practice for their interviews.
                        Start the conversation by asking: "Tell me about yourself."
                        Then, continue the interview based on their responses and the context provided below.
                        Ask relevant behavioral questions, technical questions (if applicable based on their role), and situational questions.
                        Provide constructive feedback on their answers if they ask for it or if you see clear areas for improvement.
                        Keep your responses as an interviewer concise and focused on the interview flow.

                        Here is some context about the candidate:

                        --- Candidate Summary ---
                        {st.session_state.combined_summary}

                        --- Candidate's Answers to Initial Questions ---
                        {st.session_state.initial_answers_str}

                        --- Candidate's CV (if provided) ---
                        {st.session_state.cv_text if st.session_state.cv_text else "CV not provided or text extraction failed."}

                        --- Candidate's LinkedIn Data (if provided) ---
                        {st.session_state.linkedin_data_str if st.session_state.linkedin_data_str != "Error fetching LinkedIn data" else "LinkedIn data not provided or fetch error."}

                        Begin the interview now. Your first question should be: "Tell me about yourself."
                        """
                        st.session_state.gemini_chat = model.start_chat(history=[
                            {"role": "user", "parts": [chat_context]},
                            {"role": "model", "parts": [
                                "Okay, I understand. Let's warm up with something simple, but important: Tell me about yourself."]}
                        ])
                        st.session_state.messages.append({"role": "assistant",
                                                          "content": "Okay, I understand. Let's warm up with something simple, but important: Tell me about yourself."})
                        st.rerun()  # Rerun to update the UI for the chat
                    except Exception as e:
                        st.error(f"Error initializing Gemini chat: {e}")
                        st.session_state.interview_started = False
                        st.session_state.data_processed = False  # Allow reprocessing
                else:
                    st.error("Could not start interview due to errors in data processing.")
                    st.session_state.data_processed = False  # Allow reprocessing

if st.session_state.data_processed and st.button("🔄 Reset and Start Over"):
    # Clear relevant session state variables to allow starting over
    for key in ["cv_text", "linkedin_data_str", "initial_answers_str",
                "combined_summary", "interview_started", "messages",
                "gemini_chat", "data_processed", "initial_answers_dict"]:
        if key in st.session_state:
            del st.session_state[key]
    st.rerun()

with col2:
    st.subheader("Step 3: Interview Practice")
    if not st.session_state.interview_started:
        st.info("Complete Step 1 & 2 and click 'Process My Info' to begin the interview.")

    if st.session_state.combined_summary and "Error" not in st.session_state.combined_summary:
        with st.expander("View Candidate Summary & Initial Answers", expanded=False):
            st.markdown("**Generated Candidate Summary:**")
            st.markdown(st.session_state.combined_summary)
            st.markdown("**Initial Question Answers:**")
            st.markdown(st.session_state.initial_answers_str.replace("\n", "\n\n"))  # Add more space for readability
            if st.session_state.cv_text and "Error" not in st.session_state.cv_text:
                st.markdown("**CV Text:**")
                st.text_area("CV Content", st.session_state.cv_text, height=150, disabled=True)
            if st.session_state.linkedin_data_str and "Error" not in st.session_state.linkedin_data_str and st.session_state.linkedin_data_str != "Not provided.":
                st.markdown("**LinkedIn Data:**")
                st.text_area("LinkedIn Content", st.session_state.linkedin_data_str, height=150, disabled=True)

    if st.session_state.interview_started and st.session_state.gemini_chat:
        # Display chat messages
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        # Chat input
        if prompt := st.chat_input("Your answer..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                message_placeholder = st.empty()
                full_response = ""
                try:
                    with st.spinner("Interviewer thinking..."):
                        response_stream = st.session_state.gemini_chat.send_message(prompt, stream=True)
                        for chunk in response_stream:
                            full_response += chunk.text
                            message_placeholder.markdown(full_response + "▌")
                        message_placeholder.markdown(full_response)
                    st.session_state.messages.append({"role": "assistant", "content": full_response})
                except Exception as e:
                    error_message = f"An error occurred with the Gemini API: {e}"
                    st.error(error_message)
                    st.session_state.messages.append({"role": "assistant", "content": error_message})
                    # Optionally, try to re-initialize chat or offer a retry mechanism
                    st.session_state.interview_started = False  # Stop interview on error
                    st.warning(
                        "Interview stopped due to an API error. Please check your API key and try processing again.")

    elif st.session_state.data_processed and not st.session_state.interview_started:
        st.warning("Interview could not start. Check for error messages above and try processing your info again.")
