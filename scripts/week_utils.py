from datetime import datetime, timedelta

def get_last_week():
    """Returns (since, until) for Monday-Sunday of last week."""
    today = datetime.utcnow().date()
    # Go back to last Monday
    days_since_monday = today.weekday()  # Monday=0, Sunday=6
    last_monday = today - timedelta(days=days_since_monday + 7)
    last_sunday = last_monday + timedelta(days=6)
    since = datetime.combine(last_monday, datetime.min.time())
    until = datetime.combine(last_sunday, datetime.max.time().replace(microsecond=0))
    return since, until

def get_week_before():
    """Returns (since, until) for the week before last week (for WoW comparison)."""
    since, until = get_last_week()
    return since - timedelta(days=7), until - timedelta(days=7)

def week_label(since, until):
    return f"{since.strftime('%d %b')} – {until.strftime('%d %b %Y')}"

if __name__ == "__main__":
    since, until = get_last_week()
    print(f"Last week: {week_label(since, until)}")
    since2, until2 = get_week_before()
    print(f"Week before: {week_label(since2, until2)}")
