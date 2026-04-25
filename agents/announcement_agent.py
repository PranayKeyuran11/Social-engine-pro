import os
import google.genai as genai
from graph.state import SocialState

def announcement_agent(state: SocialState) -> SocialState:
    topic = state["topic"]
    context = state.get("context", "")
    api_key = state.get("api_key") or os.getenv("GOOGLE_API_KEY")

    prompt = f"""Write a short network announcement/sharing message for:
Topic: {topic}
Context: {context}

This is for sharing with your personal network. Warm, authentic, concise (2-3 sentences).
Return ONLY the message."""

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
    return {"announcement": response.text.strip()}