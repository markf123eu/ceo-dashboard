import threading, subprocess, os

def run_scheduler():
    subprocess.run(["python3", "scheduler.py"], cwd=os.path.dirname(os.path.abspath(__file__)))

def run_webhook():
    subprocess.run(["python3", "jobber_webhook.py"], cwd=os.path.dirname(os.path.abspath(__file__)))

# Run both in parallel
t1 = threading.Thread(target=run_scheduler)
t2 = threading.Thread(target=run_webhook)
t1.start()
t2.start()
t1.join()
t2.join()
