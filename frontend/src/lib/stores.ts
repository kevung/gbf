/** Svelte 5 rune-based shared stores. */

// ── Explorer filters (persisted in URL search params via page navigation) ──────
export interface ExplorerFilters {
  player:        string;
  tournament:    string;
  away_p1:       number | null;
  away_p2:       number | null;
  phase:         string;
  decision_type: string;
  error_min:     number;
  error_max:     number;
  blunders_only: boolean;
}

export const defaultFilters = (): ExplorerFilters => ({
  player: '', tournament: '', away_p1: null, away_p2: null,
  phase: '', decision_type: '', error_min: 0, error_max: 2, blunders_only: false,
});

// ── Reactive singletons (module-level $state — Svelte 5 universal reactivity) ─
export const appState = $state({
  selectedPlayer: '' as string,
  comparePlayer:  '' as string,
  heatmapLength:  null as number | null,
  heatmapPlayer:  '' as string,
  explorerFilters: defaultFilters(),
  explorerPage:   0,
  catalogueCluster: null as number | null,
  cubeScore: { away_p1: 3, away_p2: 3, cube_value: 1, equity: 0.0, gammon_threat: 0.0 },
});
