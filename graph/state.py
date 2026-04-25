from typing import TypedDict, Optional, List

class SocialState(TypedDict):
    topic: str
    context: str
    api_key: Optional[str]
    instagram_caption: Optional[str]
    instagram_hashtags: Optional[List[str]]
    linkedin_post: Optional[str]
    linkedin_article: Optional[str]
    announcement: Optional[str]