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
                if data.get("choices") and data["choices"][0].get("message"):
                    resp.success()
                else:
                    resp.failure("Invalid response schema: missing choices or message")
            else:
                resp.failure(f"HTTP {resp.status_code}")
