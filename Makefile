.PHONY: build import deploy observe benchmark smoke clean help cluster port-forward all

CLUSTER_NAME=llm-cluster
IMAGE_NAME=llm-inference
IMAGE_TAG=v2
IMAGE=$(IMAGE_NAME):$(IMAGE_TAG)

help:
	@echo "Available targets:"
	@echo "  make build      — Build Docker image"
	@echo "  make import     — Import image into k3d cluster"
	@echo "  make deploy     — Apply Kubernetes manifests"
	@echo "  make observe    — Deploy Prometheus + Grafana observability stack"
	@echo "  make smoke      — Smoke test: liveness, readiness, and inference endpoint"
	@echo "  make benchmark  — Run Locust benchmark (headless, 10 users, 60s)"
	@echo "  make cluster     — Create k3d cluster (idempotent)"
	@echo "  make port-forward — Forward service to localhost:8000 (run in separate terminal)"
	@echo "  make all        — cluster + build + import + deploy"
	@echo "  make clean      — Delete k3d cluster"

cluster:
	k3d cluster list $(CLUSTER_NAME) >/dev/null 2>&1 || k3d cluster create $(CLUSTER_NAME) --agents 2

port-forward:
	kubectl port-forward svc/llm-inference 8000:8000

build:
	docker build -f docker/Dockerfile -t $(IMAGE) .

import:
	k3d image import $(IMAGE) -c $(CLUSTER_NAME)

deploy:
	kubectl apply -f k8s/
	kubectl rollout status deployment/llm-inference

observe:
	kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
	helm repo update
	helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
		--namespace monitoring \
		--set grafana.adminPassword=admin123 \
		--set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false
	kubectl apply -f monitoring/servicemonitor.yaml

smoke:
	@echo "--- Liveness ---"
	curl -sf http://localhost:8000/live | python3 -m json.tool
	@echo "--- Readiness ---"
	curl -sf http://localhost:8000/ready | python3 -m json.tool
	@echo "--- Inference ---"
	curl -sf http://localhost:8000/v1/chat/completions \
		-H "Content-Type: application/json" \
		-d '{"model":"phi3:mini","messages":[{"role":"user","content":"Reply with one word: ok"}],"stream":false,"max_tokens":5}' \
		| python3 -m json.tool

benchmark:
	locust -f benchmark/locustfile.py --headless -u 10 -r 2 -t 60s \
		--host http://localhost:8000 \
		--csv benchmark/results/latest

clean:
	k3d cluster delete $(CLUSTER_NAME)

all: cluster build import deploy
