/**
 * Color scales for barycentric views.
 *
 * rdbu(t) — RdBu diverging scale matching matplotlib's RdBu.
 *   t=0 → deep red (P1 losing)   t=0.5 → near-white (even)   t=1 → deep blue (P1 winning)
 *
 * colorForField(value, field) — normalises value to [0,1] then calls rdbu().
 */

// 11-stop RdBu palette (ColorBrewer, red-to-blue)
const STOPS = [
  [103,   0,  31],  // 0.0
  [178,  24,  43],  // 0.1
  [214,  96,  77],  // 0.2
  [244, 165, 130],  // 0.3
  [253, 219, 199],  // 0.4
  [247, 247, 247],  // 0.5 — neutral
  [209, 229, 240],  // 0.6
  [146, 197, 222],  // 0.7
  [ 67, 147, 195],  // 0.8
  [ 33, 102, 172],  // 0.9
  [  5,  48,  97],  // 1.0
];

/**
 * Interpolate the RdBu scale.
 * @param {number} t  value in [0, 1]
 * @returns {string}  CSS `rgb(r,g,b)`
 */
export function rdbu(t) {
  const clamped = Math.max(0, Math.min(1, t));
  const scaled  = clamped * (STOPS.length - 1);
  const lo      = Math.floor(scaled);
  const hi      = Math.min(lo + 1, STOPS.length - 1);
  const frac    = scaled - lo;

  const r = Math.round(STOPS[lo][0] + frac * (STOPS[hi][0] - STOPS[lo][0]));
  const g = Math.round(STOPS[lo][1] + frac * (STOPS[hi][1] - STOPS[lo][1]));
  const b = Math.round(STOPS[lo][2] + frac * (STOPS[hi][2] - STOPS[lo][2]));
  return `rgb(${r},${g},${b})`;
}

// Per-field value ranges for normalisation to [0,1]
const FIELD_RANGES = {
  mwc_p1:             [0,     1    ],
  cubeless_mwc_p1:    [0,     1    ],
  cube_gap_p1:        [-0.25, 0.25 ],
  cubeful_equity_p1:  [-1,    1    ],
  disp_magnitude_p1:  [0,     4    ],
};

/**
 * Map a raw field value to a CSS color string.
 * @param {number}  value
 * @param {string}  field  one of the keys in FIELD_RANGES (default: mwc_p1)
 */
export function colorForField(value, field = 'mwc_p1') {
  const [min, max] = FIELD_RANGES[field] ?? [0, 1];
  const t = (value - min) / (max - min);
  return rdbu(t);
}

/**
 * Normalise a raw value to [0,1] for the given field.
 */
export function normalizeField(value, field = 'mwc_p1') {
  const [min, max] = FIELD_RANGES[field] ?? [0, 1];
  return Math.max(0, Math.min(1, (value - min) / (max - min)));
}

export const SUPPORTED_COLOR_FIELDS = Object.keys(FIELD_RANGES);
