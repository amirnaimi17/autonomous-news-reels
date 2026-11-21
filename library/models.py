"""Read the one SQLite file. Django does not create or alter these tables."""

from django.db import models


class ExistingTable(models.Model):
    class Meta:
        abstract = True
        managed = False


class Client(ExistingTable):
    id = models.TextField(primary_key=True)
    name = models.TextField()
    timezone = models.TextField()
    daily_reel_limit = models.IntegerField()
    created_at = models.TextField()

    class Meta(ExistingTable.Meta):
        abstract = False
        managed = False
        db_table = "clients"

    def __str__(self) -> str:
        return self.name


class NewsEvent(ExistingTable):
    id = models.TextField(primary_key=True)
    client_id = models.TextField()
    title = models.TextField()
    summary = models.TextField(blank=True)
    state = models.TextField()
    story_class = models.TextField(blank=True, null=True)
    importance_score = models.FloatField(blank=True, null=True)
    article_count = models.IntegerField()
    first_published_at = models.TextField(blank=True, null=True)
    last_published_at = models.TextField(blank=True, null=True)
    source_urls_json = models.TextField(blank=True)

    class Meta(ExistingTable.Meta):
        abstract = False
        managed = False
        db_table = "news_events"
        verbose_name = "news event"

    def __str__(self) -> str:
        return self.title


class NewsArticle(ExistingTable):
    id = models.TextField(primary_key=True)
    client_id = models.TextField()
    source_name = models.TextField()
    title = models.TextField()
    canonical_url = models.TextField()
    summary = models.TextField(blank=True)
    published_at = models.TextField(blank=True, null=True)
    language = models.TextField(blank=True, null=True)
    relation = models.TextField()
    event_id = models.TextField(blank=True, null=True)

    class Meta(ExistingTable.Meta):
        abstract = False
        managed = False
        db_table = "news_articles"
        verbose_name = "news article"

    def __str__(self) -> str:
        return self.title


class EventSelection(ExistingTable):
    id = models.TextField(primary_key=True)
    client_id = models.TextField()
    event_id = models.TextField()
    production_date = models.TextField()
    rank = models.IntegerField()
    importance_score = models.FloatField()
    story_class = models.TextField(blank=True, null=True)
    created_at = models.TextField()

    class Meta(ExistingTable.Meta):
        abstract = False
        managed = False
        db_table = "event_selections"
        verbose_name = "selection"

    def __str__(self) -> str:
        return f"{self.production_date} rank {self.rank}"


class GeneratedContent(ExistingTable):
    id = models.TextField(primary_key=True)
    client_id = models.TextField()
    event_id = models.TextField()
    production_date = models.TextField()
    slot_key = models.TextField()
    state = models.TextField()
    video_path = models.TextField(blank=True, null=True)
    audio_path = models.TextField(blank=True, null=True)
    created_at = models.TextField()
    updated_at = models.TextField()

    class Meta(ExistingTable.Meta):
        abstract = False
        managed = False
        db_table = "generated_content"

    def __str__(self) -> str:
        return f"{self.production_date} {self.slot_key} {self.state}"


class DailyProduction(ExistingTable):
    id = models.TextField(primary_key=True)
    client_id = models.TextField()
    production_date = models.TextField()
    slot_key = models.TextField()
    status = models.TextField()
    event_id = models.TextField(blank=True, null=True)
    detail = models.TextField(blank=True, null=True)
    started_at = models.TextField(blank=True, null=True)
    finished_at = models.TextField(blank=True, null=True)

    class Meta(ExistingTable.Meta):
        abstract = False
        managed = False
        db_table = "daily_production"
        verbose_name = "production slot"

    def __str__(self) -> str:
        return f"{self.production_date} {self.slot_key} {self.status}"


class Page(ExistingTable):
    id = models.AutoField(primary_key=True)
    name = models.TextField()
    username = models.TextField(blank=True)
    status = models.TextField()
    created_at = models.TextField()

    class Meta(ExistingTable.Meta):
        abstract = False
        managed = False
        db_table = "pages"

    def __str__(self) -> str:
        return self.name


class Reel(ExistingTable):
    reel_id = models.TextField(primary_key=True)
    story_fingerprint = models.TextField()
    target_page = models.TextField()
    title = models.TextField()
    category = models.TextField(blank=True)
    affected_audience = models.TextField(blank=True)
    editorial_angle = models.TextField(blank=True)
    caption_fa = models.TextField(blank=True)
    video_path = models.TextField(blank=True)
    duration_seconds = models.FloatField(blank=True, null=True)
    width = models.IntegerField(blank=True, null=True)
    height = models.IntegerField(blank=True, null=True)
    checksum_sha256 = models.TextField(blank=True, null=True)
    local_status = models.TextField()
    facts_checked_at = models.TextField(blank=True, null=True)
    error_message = models.TextField(blank=True)
    created_at = models.TextField()
    updated_at = models.TextField()

    class Meta(ExistingTable.Meta):
        abstract = False
        managed = False
        db_table = "reels"

    def __str__(self) -> str:
        return self.title


class Post(ExistingTable):
    id = models.AutoField(primary_key=True)
    page = models.ForeignKey(Page, db_column="page_id", on_delete=models.DO_NOTHING)
    reel = models.ForeignKey(Reel, db_column="reel_id", on_delete=models.DO_NOTHING, to_field="reel_id")
    title = models.TextField()
    description = models.TextField(blank=True)
    status = models.TextField()
    scheduled_for = models.TextField(blank=True, null=True)
    created_at = models.TextField()
    updated_at = models.TextField()

    class Meta(ExistingTable.Meta):
        abstract = False
        managed = False
        db_table = "posts"

    def __str__(self) -> str:
        return self.title


class PostVideo(ExistingTable):
    id = models.AutoField(primary_key=True)
    post = models.ForeignKey(Post, db_column="post_id", on_delete=models.DO_NOTHING, related_name="videos")
    path = models.TextField()
    checksum_sha256 = models.TextField(blank=True)
    duration_seconds = models.FloatField(blank=True, null=True)
    width = models.IntegerField(blank=True, null=True)
    height = models.IntegerField(blank=True, null=True)
    status = models.TextField()
    created_at = models.TextField()

    class Meta(ExistingTable.Meta):
        abstract = False
        managed = False
        db_table = "post_videos"
        verbose_name = "video"

    def __str__(self) -> str:
        return self.path


class CronJobLog(ExistingTable):
    id = models.AutoField(primary_key=True)
    job_name = models.TextField()
    status = models.TextField()
    message = models.TextField()
    detail_json = models.TextField(blank=True)
    created_at = models.TextField()

    class Meta(ExistingTable.Meta):
        abstract = False
        managed = False
        db_table = "cron_job_logs"
        verbose_name = "cron run"

    def __str__(self) -> str:
        return f"{self.job_name} {self.status}"


class GenerationAttempt(ExistingTable):
    id = models.AutoField(primary_key=True)
    started_at = models.TextField()
    finished_at = models.TextField(blank=True, null=True)
    target_page = models.TextField()
    slot_local = models.TextField(blank=True, null=True)
    status = models.TextField()
    reel_id = models.TextField(blank=True, null=True)
    message = models.TextField(blank=True)

    class Meta(ExistingTable.Meta):
        abstract = False
        managed = False
        db_table = "generation_attempts"
        verbose_name = "generation attempt"

    def __str__(self) -> str:
        return f"{self.slot_local or self.started_at} {self.status}"
