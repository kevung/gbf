# GBF Explorer

Minimal data exploration UI for the GBF backgammon position database.

## Quick Start

```bash
# 1. Build the frontend
cd explorer && npm install && npm run build && cd ..

# 2. Run the server
go run ./cmd/explorer -db bmab.db -bmab data/bmab-2025-06-23

# 3. Open http://localhost:8080
```

## Views

| View | Description |
|------|-------------|
| **Dashboard** | DB stats, class distribution pie chart, score distribution bar chart, projection runs |
| **Projections** | UMAP/PCA 2D scatter plots, colored by cluster/class/score, click for position detail |
| **Explorer** | Feature scatter (X vs Y), histogram, box plot, correlation matrix — any of 44 features |
| **Import** | Progressive BMAB import with configurable proportion, real-time progress via SSE |
| **Help** | Built-in documentation, feature reference, API endpoints |

## Server Flags

| Flag | Default | Description |
|------|---------|-------------|
| `-db` | `bmab.db` | SQLite database path |
| `-bmab` | *(none)* | BMAB dataset directory (enables import) |
| `-addr` | `:8080` | Listen address |
| `-static` | `explorer/dist` | Frontend static files directory |

## Development

```bash
# Terminal 1: Go API server
go run ./cmd/explorer -db bmab.db -bmab data/bmab-2025-06-23

# Terminal 2: Vite dev server (hot reload)
cd explorer && npm run dev
```

The Vite dev server proxies `/api/` requests to `localhost:8080`.

## Tech Stack

- **Backend**: Go (net/http, existing GBF library)
- **Frontend**: Svelte 5 + Vite
- **Charts**: Apache ECharts (canvas renderer, handles 50K+ points)
- **Style**: Custom CSS, dark theme
