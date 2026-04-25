import os
import google.genai as genai
from graph.state import SocialState

def linkedin_article_agent(state: SocialState) -> SocialState:
    topic = state["topic"]
    context = state.get("context", "")
    api_key = state.get("api_key") or os.getenv("GOOGLE_API_KEY")

    prompt = f"""Write a LinkedIn long-form article on:
Topic: {topic}
Context: {context}

Structure: Title, Introduction, 3 key sections with subheadings, Conclusion.
Professional but conversational. ~400 words.
Return ONLY the article."""

    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    return {"linkedin_article": response.text.strip()}