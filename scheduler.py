import schedule, time, subprocess, os

def run_weekly():
    print("Running weekly report...")
    subprocess.run(["python3", "scripts/run_report.py"], cwd=os.path.dirname(os.path.abspath(__file__)))

def run_daily():
    print("Running daily report...")
    subprocess.run(["python3", "scripts/daily_report.py"], cwd=os.path.dirname(os.path.abspath(__file__)))

# Weekly report — Monday 8am
schedule.every().monday.at("08:00").do(run_weekly)

# Daily report — every day at 4pm
schedule.every().day.at("16:00").do(run_daily)

print("Scheduler running...")
while True:
    schedule.run_pending()
    time.sleep(60)
