import json
from locust import HttpUser, task, between

PROMPT = (
    "Explain the concept of Kubernetes horizontal pod autoscaling "
    "in two sentences."
)

class LLMUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def chat_completion(self):
        payload = {
            "model": "phi3:mini",
            "messages": [{"role": "user", "content": PROMPT}],
            "stream": False,
            "max_tokens": 50,
        }
        with self.client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Content-Type": "application/json"},
            catch_response=True,
            timeout=120,
        ) as resp:
            if resp.status_code == 200:
                data = resp.json()
                tokens = data.get("usage", {}).get("total_tokens", 0)
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")
