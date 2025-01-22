

from api import WordPressAPI
import json

wp = WordPressAPI("")
# posts = wp.get_posts()
# print(posts)
comments = wp.get_comments()

print(comments.data)
print(comments.total_count)
print(comments.total_pages_count)