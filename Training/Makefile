# Matrix/Training/Makefile

PROJECT ?= cameltrain
IMAGE ?= gcr.io/$(PROJECT)/matrix-trainer:latest
SERVICE_ACCOUNT ?= sight-service-account@cameltrain.iam.gserviceaccount.com
BUCKET ?= matrix_model

# Number of tasks should match the number of Forest Types (33 found in training set)
TASKS ?= 33

.PHONY: help docker-build docker-push deploy-cloud execute-cloud

help:
	@echo "MATRIX Training Pipeline Makefile"
	@echo ""
	@echo "Targets:"
	@echo "  docker-build       - Build the Docker image natively from the repository root"
	@echo "  docker-push        - Push the Docker image to GCR"
	@echo "  deploy-cloud       - Create the Cloud Run Job"
	@echo "  execute-cloud      - Generate task map and execute the job"

docker-build:
	cd .. && docker build -t $(IMAGE) -f Training/Dockerfile .

docker-push:
	docker push $(IMAGE)

deploy-cloud:
	-gcloud run jobs delete matrix-train --region us-central1 --quiet 2>/dev/null || true
	gcloud run jobs create matrix-train \
		--image $(IMAGE) \
		--tasks $(TASKS) \
		--max-retries 3 \
		--region us-central1 \
		--memory 32Gi \
		--cpu 8 \
		--task-timeout=10800s \
		--execution-environment gen2 \
		--service-account $(SERVICE_ACCOUNT) \
		--args="--cloud","--bucket=$(BUCKET)"

execute-cloud:
	uv run python3 generate_training_task_map.py --bucket="$(BUCKET)"
	gcloud run jobs execute matrix-train --region us-central1
