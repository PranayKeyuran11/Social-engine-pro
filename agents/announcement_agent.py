import os
import google.genai as genai
from graph.state import SocialState

def announcement_agent(state: SocialState) -> SocialState:
    topic = state["topic"]
    context = state.get("context", "")

    prompt = f"""Write a short network announcement/sharing message for:
Topic: {topic}
Context: {context}

This is for sharing with your personal network. Warm, authentic, concise (2-3 sentences).
Return ONLY the message."""

    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    response = client.models.generate_content(model="gemini-3.1-flash-lite-preview", contents=prompt)
    return {"announcement": response.text.strip()}