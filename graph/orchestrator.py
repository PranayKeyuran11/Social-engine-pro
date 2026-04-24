from langgraph.graph import StateGraph, START, END
from graph.state import SocialState
from agents.instagram_agent import instagram_agent
from agents.linkedin_post_agent import linkedin_post_agent
from agents.linkedin_article_agent import linkedin_article_agent
from agents.announcement_agent import announcement_agent

def build_graph():
    graph = StateGraph(SocialState)

    graph.add_node("instagram_agent", instagram_agent)
    graph.add_node("linkedin_post_agent", linkedin_post_agent)
    graph.add_node("linkedin_article_agent", linkedin_article_agent)
    graph.add_node("announcement_agent", announcement_agent)

    graph.add_edge(START, "instagram_agent")
    graph.add_edge(START, "linkedin_post_agent")
    graph.add_edge(START, "linkedin_article_agent")
    graph.add_edge(START, "announcement_agent")

    graph.add_edge("instagram_agent", END)
    graph.add_edge("linkedin_post_agent", END)
    graph.add_edge("linkedin_article_agent", END)
    graph.add_edge("announcement_agent", END)

    return graph.compile()