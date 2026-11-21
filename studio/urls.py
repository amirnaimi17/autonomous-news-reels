from django.contrib import admin
from django.urls import path

admin.site.site_header = "News Reels"
admin.site.site_title = "News Reels"
admin.site.index_title = "Stories, reels, posts, and cron runs"

urlpatterns = [
    path("", admin.site.urls),
]
