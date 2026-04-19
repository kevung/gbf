# GBF Explorer — Build System
#
# Build a standalone executable that embeds the Svelte UI.
# The only requirements are: Go 1.22+, Node.js 18+ (for building the UI).
#
# Usage:
#   make              # build for current OS
#   make all          # build for Linux + Windows
#   make clean        # remove build artifacts
#   make dev          # run in dev mode (hot reload)

BINARY_NAME  := gbf-explorer
BUILD_DIR    := bin
EXPLORER_DIR := explorer
STATIC_DIR   := cmd/explorer/static
GO_CMD       := cmd/explorer

# Go build flags for smaller binary.
LDFLAGS := -s -w
GOFLAGS := -trimpath

.PHONY: all clean dev build build-linux build-windows ui bary-service help

# Default: build for current platform.
build: ui go-build

# Build for all platforms.
all: ui build-linux build-windows
	@echo ""
	@echo "Built executables:"
	@ls -lh $(BUILD_DIR)/$(BINARY_NAME)*

# Build the Svelte UI and copy to the static embed directory.
ui:
	@echo "==> Building Svelte UI..."
	cd $(EXPLORER_DIR) && npm install && npm run build
	@echo "==> Copying dist → $(STATIC_DIR)..."
	rm -rf $(STATIC_DIR)
	cp -r $(EXPLORER_DIR)/dist $(STATIC_DIR)
	@echo "==> UI ready."

# Build Go binary for current platform.
go-build:
	@mkdir -p $(BUILD_DIR)
	@echo "==> Building $(BINARY_NAME) for $$(go env GOOS)/$$(go env GOARCH)..."
	go build $(GOFLAGS) -ldflags "$(LDFLAGS)" -o $(BUILD_DIR)/$(BINARY_NAME) ./$(GO_CMD)
	@echo "==> $(BUILD_DIR)/$(BINARY_NAME) ready."

# Cross-compile for Linux amd64.
build-linux: ui
	@mkdir -p $(BUILD_DIR)
	@echo "==> Building $(BINARY_NAME) for linux/amd64..."
	GOOS=linux GOARCH=amd64 go build $(GOFLAGS) -ldflags "$(LDFLAGS)" \
		-o $(BUILD_DIR)/$(BINARY_NAME)-linux-amd64 ./$(GO_CMD)

# Cross-compile for Windows amd64.
build-windows: ui
	@mkdir -p $(BUILD_DIR)
	@echo "==> Building $(BINARY_NAME) for windows/amd64..."
	GOOS=windows GOARCH=amd64 go build $(GOFLAGS) -ldflags "$(LDFLAGS)" \
		-o $(BUILD_DIR)/$(BINARY_NAME)-windows-amd64.exe ./$(GO_CMD)

# Dev mode: run Go server + Svelte dev server with hot reload.
dev:
	@echo "==> Starting dev mode..."
	@echo "    Start the Go server:   go run ./$(GO_CMD) -db bmab.db -static $(EXPLORER_DIR)/dist"
	@echo "    Start Svelte dev:      cd $(EXPLORER_DIR) && npm run dev"

clean:
	rm -rf $(BUILD_DIR)/$(BINARY_NAME)*
	rm -rf $(STATIC_DIR)
	rm -rf $(EXPLORER_DIR)/dist
	rm -rf $(EXPLORER_DIR)/node_modules

bary-service:
	python scripts/barycentric_service.py \
		--bary    data/barycentric/barycentric_v2.parquet \
		--cells   data/barycentric/cell_keys.parquet \
		--boot    data/barycentric/bootstrap_cells.parquet \
		--enriched data/parquet/positions_enriched \
		--games   data/parquet/games.parquet \
		--matches data/parquet/matches.parquet \
		--port    8100

help:
	@echo "GBF Explorer Build System"
	@echo ""
	@echo "Targets:"
	@echo "  make              Build for current platform"
	@echo "  make all          Build for Linux + Windows"
	@echo "  make ui           Build only the Svelte UI"
	@echo "  make build-linux  Cross-compile for Linux"
	@echo "  make build-windows Cross-compile for Windows"
	@echo "  make dev          Show dev mode instructions"
	@echo "  make clean        Remove build artifacts"
