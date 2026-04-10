/** Typed fetch wrappers for the GBF Dashboard API. */

const BASE = '/api';

async function get<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
  const url = new URL(BASE + path, window.location.origin);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v));
    }
  }
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json() as Promise<T>;
}

// ── Types ──────────────────────────────────────────────────────────────────────
export interface PlayerSummary {
  player_name: string; total_games: number; total_positions: number;
  avg_error_checker: number; avg_error_cube: number; blunder_rate: number;
}
export interface PlayerProfile extends PlayerSummary {
  pr_rating?: number; pr_rank?: number; pr_ci_low?: number; pr_ci_high?: number;
  cluster_id?: number; archetype_label?: string;
  contact_error?: number; race_error?: number; bearoff_error?: number;
  missed_double_rate?: number; wrong_take_rate?: number; consistency_score?: number;
}
export interface Position {
  match_id: string; move_number: number; player_name: string; tournament?: string;
  away_p1: number; away_p2: number; match_phase: number; decision_type: string;
  move_played_error: number; eval_equity: number; cluster_id?: number;
}
export interface HeatmapCell {
  away_p1: number; away_p2: number; avg_error: number; n_decisions: number;
  missed_double_rate: number; wrong_take_rate: number; wrong_pass_rate: number;
}
export interface Cluster {
  cluster_id: number; archetype_label: string; position_count: number;
  avg_error: number; dominant_phase: number;
}
export interface Threshold {
  away_p1: string; away_p2: string; cube_value: string;
  double_threshold: string; pass_threshold: string;
}
export interface Ranking {
  player_name: string; rating: number; pr_rating: number; pr_rank: number;
  total_games: number; blunder_rate: number;
}
export interface Overview { total_positions?: number; avg_error?: number; blunder_rate?: number; [k: string]: unknown }

// ── Player endpoints ───────────────────────────────────────────────────────────
export const api = {
  players: {
    list:    (p?: { search?: string; limit?: number; offset?: number }) =>
               get<{ players: PlayerSummary[] }>('/players', p),
    profile: (name: string) => get<PlayerProfile>(`/players/${encodeURIComponent(name)}/profile`),
    positions: (name: string, p?: Record<string, unknown>) =>
               get<{ positions: Position[] }>(`/players/${encodeURIComponent(name)}/positions`, p as never),
    compare: (p1: string, p2: string) =>
               get<{ p1: PlayerProfile; p2: PlayerProfile }>('/players/compare', { p1, p2 }),
  },

  tournaments: {
    list:  (search?: string) => get<{ tournaments: unknown[] }>('/tournaments', { search }),
    stats: (name: string)    => get<{ stats: unknown }>(`/tournaments/${encodeURIComponent(name)}/stats`),
  },

  heatmap: {
    cubeError: (p?: { match_length?: number; player?: string }) =>
               get<{ cells: HeatmapCell[] }>('/heatmap/cube-error', p),
    cell:      (away_p1: number, away_p2: number, match_length?: number) =>
               get<{ cell: HeatmapCell; top_positions: Position[] }>(
                 '/heatmap/cube-error/cell', { away_p1, away_p2, match_length }),
  },

  positions: {
    search: (p: Record<string, unknown>) => get<{ positions: Position[] }>('/positions', p as never),
    detail: (id: string) => get<{ position: Position; cluster: Cluster | null }>(`/positions/${id}/detail`),
  },

  cube: {
    thresholds:     (p?: { away_p1?: number; away_p2?: number; cube_value?: number }) =>
                    get<{ thresholds: Threshold[] }>('/cube/thresholds', p),
    recommendation: (p: { away_p1: number; away_p2: number; cube_value: number; equity: number; gammon_threat: number }) =>
                    get<{ action: string; distance: number; gammon_adj_action: string; heuristics: unknown[] }>('/cube/recommendation', p),
    gammonValues:   (p?: { away_p1?: number; away_p2?: number }) =>
                    get<{ gammon_values: unknown[] }>('/cube/gammon-values', p),
  },

  stats: {
    overview:          () => get<Overview>('/stats/overview'),
    errorDistribution: (decision_type?: string) =>
                       get<{ bins: unknown[] }>('/stats/error-distribution', { decision_type }),
    rankings:          (p?: { metric?: string; limit?: number; offset?: number; search?: string }) =>
                       get<{ rankings: Ranking[] }>('/stats/rankings', p),
    temporal:          () => get<{ series: unknown[] }>('/stats/temporal'),
    overUnder:         () => get<{ performers: unknown[] }>('/stats/over-under-performers'),
  },

  clusters: {
    list:       () => get<{ clusters: Cluster[] }>('/clusters'),
    profile:    (id: number) => get<{ profile: Cluster; error_distribution: unknown[] }>(`/clusters/${id}/profile`),
    positions:  (id: number, p?: { traps_only?: boolean; limit?: number }) =>
                get<{ positions: Position[] }>(`/clusters/${id}/positions`, p),
    heuristics: (id: number) => get<{ heuristics: unknown[] }>(`/clusters/${id}/heuristics`),
  },

  map: {
    points:  (p: { x_min: number; x_max: number; y_min: number; y_max: number; limit?: number }) =>
             get<{ points: unknown[] }>('/map/points', p),
    hexbins: (p: { x_min: number; x_max: number; y_min: number; y_max: number; resolution?: number; color_by?: string }) =>
             get<{ hexbins: unknown[] }>('/map/hexbins', p),
    trajectories:       (hash: string, p?: { limit?: number; player?: string }) =>
                        get<{ trajectories: unknown[] }>(`/trajectories/${hash}`, p),
    trajectoryDetail:   (hash: string) => get<{ stats: unknown; continuations: unknown[] }>(`/trajectories/${hash}/detail`),
    trajectoryCompare:  (hash: string, player1: string, player2: string) =>
                        get<{ player1: unknown; player2: unknown }>('/trajectories/compare', { hash, player1, player2 }),
  },
};
