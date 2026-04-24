import os
from dotenv import load_dotenv
from graph.orchestrator import build_graph

load_dotenv()

def main():
    graph = build_graph()

    # ✏️ Change topic and context here anytime
    initial_state = {
        "topic": "The rise of AI agents in 2025",
        "context": "Focus on how LangGraph enables multi-agent workflows for businesses",
        "instagram_caption": None,
        "instagram_hashtags": None,
        "linkedin_post": None,
        "linkedin_article": None,
        "announcement": None,
    }

    print("🚀 Running Social Engine...\n")
    result = graph.invoke(initial_state)

    print("=" * 60)
    print("📸 INSTAGRAM CAPTION")
    print("=" * 60)
    print(result["instagram_caption"])
    print("Hashtags:", " ".join(result["instagram_hashtags"]))

    print("\n" + "=" * 60)
    print("💼 LINKEDIN POST")
    print("=" * 60)
    print(result["linkedin_post"])

    print("\n" + "=" * 60)
    print("📝 LINKEDIN ARTICLE")
    print("=" * 60)
    print(result["linkedin_article"])

    print("\n" + "=" * 60)
    print("📣 ANNOUNCEMENT")
    print("=" * 60)
    print(result["announcement"])

if __name__ == "__main__":
    main()