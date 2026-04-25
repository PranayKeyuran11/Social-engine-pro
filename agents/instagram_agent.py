import os
import google.genai as genai
from graph.state import SocialState
from tools.hashtag_generator import generate_hashtags

def instagram_agent(state: SocialState) -> SocialState:
    topic = state["topic"]
    context = state.get("context", "")

    prompt = f"""Write an engaging Instagram caption for this topic:
Topic: {topic}
Context: {context}

Make it punchy, use emojis, and keep it under 150 characters.
Return ONLY the caption text."""

    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    response = client.models.generate_content(model="gemini-1.5-flash", contents=prompt)
    caption = response.text.strip()

    hashtags = generate_hashtags.invoke({"topic": topic, "platform": "instagram"})

    return {
        "instagram_caption": caption,
        "instagram_hashtags": hashtags,
    }