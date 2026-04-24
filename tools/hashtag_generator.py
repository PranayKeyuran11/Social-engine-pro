from langchain_core.tools import tool

@tool
def generate_hashtags(topic: str, platform: str = "instagram") -> list[str]:
    """Generate platform-aware hashtags for a given topic."""
    base = topic.lower().replace(" ", "")
    words = topic.lower().split()

    if platform == "instagram":
        tags = [f"#{base}", "#reels", "#instagood", "#viral"]
        tags += [f"#{w}" for w in words if len(w) > 3]
        return tags[:15]
    elif platform == "linkedin":
        tags = [f"#{w.capitalize()}" for w in words if len(w) > 3]
        tags += ["#ProfessionalDevelopment", "#Insights"]
        return tags[:5]
    else:
        return [f"#{base}"]