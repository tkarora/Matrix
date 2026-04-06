# Matrix/Evaluate/Makefile

PROJECT ?= cameltrain
IMAGE ?= gcr.io/$(PROJECT)/matrix-evaluator:latest
RUN_ID ?= matrix-v1-run-$(shell date +%Y%m%d-%H%M%S)
SERVICE_ACCOUNT ?= sight-service-account@cameltrain.iam.gserviceaccount.com

# Local paths
LOCAL_MODELS_DIR ?= ../Models/matrix_models
LOCAL_BIOMASS ?= ../Models/matrix_models/FT_biomass_kg_0227_Mitra.csv

# Cloud Run Task Counts
TEST_TASKS ?= 100
VAL_TASKS ?= 100
FULL_TASKS ?= 500

# Default models path (Jingjing's baseline)
EVAL_MODELS ?= /mnt/kokua-data/Forest/Matrix/model

.PHONY: help eval-local-test eval-local-val eval-local-full docker-build docker-push deploy-cloud-test deploy-cloud-val deploy-cloud-full execute-cloud-test execute-cloud-val execute-cloud-full

help:
	@echo "MATRIX Evaluation Pipeline Makefile"
	@echo ""
	@echo "Local execution:"
	@echo "  make eval-local-test    - Run evaluator locally against the Test split"
	@echo "  make eval-local-val     - Run evaluator locally against the Validation split"
	@echo "  make eval-local-full    - Run evaluator locally against the FULL unsplit dataset"
	@echo ""
	@echo "Cloud native (Cloud Run Array Jobs):"
	@echo "  make docker-build       - Build the Docker image natively from the repository root and push it"
	@echo "  make deploy-cloud-test  - Supply the parallel Test evaluation array to GCP"
	@echo "  make deploy-cloud-val   - Supply the parallel Validation evaluation array to GCP"
	@echo "  make deploy-cloud-full  - Supply the parallel FULL evaluation array to GCP"
	@echo "  make execute-cloud-test - Execute the deployed Test array"
	@echo "  make execute-cloud-val  - Execute the deployed Validation array"
	@echo "  make execute-cloud-full - Execute the deployed FULL array"

eval-local-test:
	python3 evaluate_model.py \
		--models="$(LOCAL_MODELS_DIR)" \
		--biomass="$(LOCAL_BIOMASS)" \
		--run-id="$(RUN_ID)-test" \
		--test

eval-local-val:
	python3 evaluate_model.py \
		--models="$(LOCAL_MODELS_DIR)" \
		--biomass="$(LOCAL_BIOMASS)" \
		--run-id="$(RUN_ID)-val" \
		--val

eval-local-full:
	python3 evaluate_model.py \
		--models="$(LOCAL_MODELS_DIR)" \
		--biomass="$(LOCAL_BIOMASS)" \
		--run-id="$(RUN_ID)-full"

docker-build:
	cd .. && docker build -t $(IMAGE) -f Evaluate/Dockerfile .

docker-push:
	docker push $(IMAGE)

deploy-cloud-test:
	-gcloud run jobs delete matrix-eval-test-split --region us-central1 --quiet 2>/dev/null || true
	gcloud run jobs create matrix-eval-test-split \
		--image $(IMAGE) \
		--tasks $(TEST_TASKS) \
		--max-retries 3 \
		--region us-central1 \
		--memory 16Gi \
		--cpu 4 \
		--task-timeout=3600s \
		--execution-environment gen2 \
		--service-account $(SERVICE_ACCOUNT) \
		--add-volume=name=kokua-data,type=cloud-storage,bucket=kokua-data \
		--add-volume-mount=volume=kokua-data,mount-path=/mnt/kokua-data \
		--add-volume=name=matrix-model,type=cloud-storage,bucket=matrix_model \
		--add-volume-mount=volume=matrix-model,mount-path=/mnt/matrix-model \
		--args="--run-id=$(RUN_ID)-test","--cloud","--test","--models=$(EVAL_MODELS)"

deploy-cloud-test-fia:
	$(MAKE) deploy-cloud-test EVAL_MODELS=/mnt/matrix-model/retrained_models

deploy-cloud-val:
	-gcloud run jobs delete matrix-eval-val-split --region us-central1 --quiet 2>/dev/null || true
	gcloud run jobs create matrix-eval-val-split \
		--image $(IMAGE) \
		--tasks $(VAL_TASKS) \
		--max-retries 3 \
		--region us-central1 \
		--memory 16Gi \
		--cpu 4 \
		--task-timeout=3600s \
		--execution-environment gen2 \
		--service-account $(SERVICE_ACCOUNT) \
		--add-volume=name=kokua-data,type=cloud-storage,bucket=kokua-data \
		--add-volume-mount=volume=kokua-data,mount-path=/mnt/kokua-data \
		--args="--run-id=$(RUN_ID)-val","--cloud","--val"

deploy-cloud-full:
	-gcloud run jobs delete matrix-eval-full-split --region us-central1 --quiet 2>/dev/null || true
	gcloud run jobs create matrix-eval-full-split \
		--image $(IMAGE) \
		--tasks $(FULL_TASKS) \
		--max-retries 3 \
		--region us-central1 \
		--memory 16Gi \
		--cpu 4 \
		--task-timeout=3600s \
		--execution-environment gen2 \
		--service-account $(SERVICE_ACCOUNT) \
		--add-volume=name=kokua-data,type=cloud-storage,bucket=kokua-data \
		--add-volume-mount=volume=kokua-data,mount-path=/mnt/kokua-data \
		--args="--run-id=$(RUN_ID)-full","--cloud"

execute-cloud-test:
	uv run python3 generate_task_map.py --bucket="matrix_model" --test --tasks $(TEST_TASKS)
	gcloud run jobs execute matrix-eval-test-split

execute-cloud-val:
	uv run python3 generate_task_map.py --bucket="matrix_model" --val --tasks $(VAL_TASKS)
	gcloud run jobs execute matrix-eval-val-split

execute-cloud-full:
	uv run python3 generate_task_map.py --bucket="matrix_model" --tasks $(FULL_TASKS)
	gcloud run jobs execute matrix-eval-full-split
