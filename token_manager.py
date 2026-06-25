import os, requests

RENDER_API_KEY       = os.getenv("RENDER_API_KEY")
RENDER_WEB_SERVICE   = "srv-d6q258qa214c73a6oij0"
RENDER_WORKER_SERVICE = "srv-d6rvnbsr85hc738lr85g"

RENDER_HEADERS = {
    "Authorization": f"Bearer {RENDER_API_KEY}",
    "Content-Type": "application/json",
}

def update_render_env(service_id, key, value):
    """Update a single environment variable on a Render service."""
    # First get existing env vars
    resp = requests.get(
        f"https://api.render.com/v1/services/{service_id}/env-vars",
        headers=RENDER_HEADERS
    )
    if resp.status_code != 200:
        print(f"  ⚠️  Failed to get env vars for {service_id}: {resp.text}", flush=True)
        return False

    env_vars = resp.json()
    
    # Update the specific key
    updated = False
    for var in env_vars:
        if var.get("envVar", {}).get("key") == key:
            var["envVar"]["value"] = value
            updated = True
            break
    
    if not updated:
        env_vars.append({"envVar": {"key": key, "value": value}})

    # Put updated env vars back
    payload = [{"key": v["envVar"]["key"], "value": v["envVar"]["value"]} for v in env_vars]
    resp2 = requests.put(
        f"https://api.render.com/v1/services/{service_id}/env-vars",
        headers=RENDER_HEADERS,
        json=payload
    )
    if resp2.status_code == 200:
        print(f"  ✅ Updated {key} on {service_id}", flush=True)
        return True
    else:
        print(f"  ❌ Failed to update {key} on {service_id}: {resp2.text}", flush=True)
        return False

def persist_jobber_tokens(access_token, refresh_token):
    """Save new Jobber tokens to both Render services."""
    print("Persisting Jobber tokens to Render...", flush=True)
    for service_id in [RENDER_WEB_SERVICE, RENDER_WORKER_SERVICE]:
        update_render_env(service_id, "JOBBER_ACCESS_TOKEN", access_token)
        update_render_env(service_id, "JOBBER_REFRESH_TOKEN", refresh_token)
    print("✅ Tokens persisted to both services", flush=True)

if __name__ == "__main__":
    print("Token manager ready")
