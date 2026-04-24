from typing import TypedDict, Optional

class SocialState(TypedDict):
    topic: str
    context: Optional[str]
    instagram_caption: Optional[str]
    instagram_hashtags: Optional[list[str]]
    linkedin_post: Optional[str]
    linkedin_article: Optional[str]
    announcement: Optional[str]