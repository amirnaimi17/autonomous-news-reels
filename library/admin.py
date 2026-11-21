from django.contrib import admin

from .models import (
    Client,
    CronJobLog,
    DailyProduction,
    EventSelection,
    GeneratedContent,
    GenerationAttempt,
    NewsArticle,
    NewsEvent,
    Page,
    Post,
    PostVideo,
    Reel,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    """News history stays visible and is not edited from the browser."""

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


class PostVideoInline(admin.TabularInline):
    model = PostVideo
    extra = 0
    can_delete = False
    fields = ("path", "status", "width", "height", "duration_seconds", "checksum_sha256")
    readonly_fields = fields


@admin.register(Client)
class ClientAdmin(ReadOnlyAdmin):
    list_display = ("name", "timezone", "daily_reel_limit", "created_at")


@admin.register(NewsEvent)
class NewsEventAdmin(ReadOnlyAdmin):
    list_display = ("title", "state", "story_class", "importance_score", "article_count", "last_published_at")
    list_filter = ("state", "story_class")
    search_fields = ("title", "summary", "id")


@admin.register(NewsArticle)
class NewsArticleAdmin(ReadOnlyAdmin):
    list_display = ("title", "source_name", "language", "published_at", "relation")
    list_filter = ("source_name", "language", "relation")
    search_fields = ("title", "canonical_url", "summary")


@admin.register(EventSelection)
class EventSelectionAdmin(ReadOnlyAdmin):
    list_display = ("production_date", "rank", "event_id", "importance_score", "story_class")
    list_filter = ("production_date", "story_class")
    search_fields = ("event_id",)


@admin.register(GeneratedContent)
class GeneratedContentAdmin(ReadOnlyAdmin):
    list_display = ("production_date", "slot_key", "state", "event_id", "updated_at")
    list_filter = ("state", "production_date")


@admin.register(DailyProduction)
class DailyProductionAdmin(ReadOnlyAdmin):
    list_display = ("production_date", "slot_key", "status", "event_id", "finished_at")
    list_filter = ("status", "production_date")


@admin.register(Page)
class PageAdmin(ReadOnlyAdmin):
    list_display = ("name", "username", "status", "created_at")


@admin.register(Reel)
class ReelAdmin(ReadOnlyAdmin):
    list_display = ("title", "local_status", "target_page", "duration_seconds", "width", "height", "updated_at")
    list_filter = ("local_status", "target_page", "category")
    search_fields = ("title", "reel_id", "editorial_angle", "caption_fa")
    readonly_fields = ("caption_fa", "video_path", "checksum_sha256", "facts_checked_at", "error_message")


@admin.register(Post)
class PostAdmin(ReadOnlyAdmin):
    list_display = ("title", "page", "status", "updated_at")
    list_filter = ("status", "page")
    search_fields = ("title", "description")
    inlines = [PostVideoInline]


@admin.register(PostVideo)
class PostVideoAdmin(ReadOnlyAdmin):
    list_display = ("post", "status", "width", "height", "duration_seconds")
    list_filter = ("status",)
    search_fields = ("path", "checksum_sha256")


@admin.register(CronJobLog)
class CronJobLogAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "job_name", "status", "message")
    list_filter = ("job_name", "status")
    search_fields = ("message", "detail_json")


@admin.register(GenerationAttempt)
class GenerationAttemptAdmin(ReadOnlyAdmin):
    list_display = ("started_at", "slot_local", "target_page", "status", "reel_id", "message")
    list_filter = ("status", "target_page")
    search_fields = ("message", "reel_id")
