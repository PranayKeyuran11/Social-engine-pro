import os
import google.genai as genai
from graph.state import SocialState

def linkedin_post_agent(state: SocialState) -> SocialState:
    topic = state["topic"]
    context = state.get("context", "")

    prompt = f"""Write a short LinkedIn post (3-5 sentences) on:
Topic: {topic}
Context: {context}

Professional tone, add a thought-provoking question at the end.
Return ONLY the post text."""

    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    response = client.models.generate_content(model="gemini-3.1-flash-lite preview", contents=prompt)
    return {"linkedin_post": response.text.strip()}