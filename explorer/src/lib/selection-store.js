/**
 * BE.8 — Shared selection state and match-in-focus store.
 * Updated by BE.5/BE.6 rect selections; consumed by SelectionPanel and BE.7.
 */
import { writable } from 'svelte/store';

export const selectionStore = writable({
  mode:      null,   // 'global' | 'cell'
  cell_id:   null,
  rect:      null,
  filters:   null,
  total:     0,
  positions: [],
  loading:   false,
});

export const matchInFocus = writable(null);   // position_id

export function clearSelection() {
  selectionStore.set({
    mode: null, cell_id: null, rect: null,
    filters: null, total: 0, positions: [], loading: false,
  });
}
