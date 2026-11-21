"""Scheduled Reel generation.

django-crontab calls this the same way social_media calls its daily jobs.
The run is generation only. It does not publish to Instagram.
"""

from app.reels.commands import generate_reel_command


def generate_scheduled_reel():
    """One Berlin slot: 07:00, 11:00, 15:00, or 19:00."""

    return generate_reel_command(scheduled=True, target="almanyar")
