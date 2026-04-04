<script>
  /**
   * Pure SVG backgammon board renderer.
   * Props: board (int[24], +N=X, -N=O), barX, barO, borneOffX, borneOffO,
   *        cubeLog2, cubeOwner, awayX, awayO, sideToMove
   */
  let {
    board = Array(24).fill(0),
    barX = 0, barO = 0,
    borneOffX = 0, borneOffO = 0,
    cubeLog2 = 0, cubeOwner = 0,
    awayX = 0, awayO = 0,
    sideToMove = 0,
  } = $props();

  // Board geometry
  const W = 480, H = 360;
  const BORDER = 12;
  const BAR_W = 24;
  const TRAY_W = 28;
  const POINT_W = (W - 2 * BORDER - BAR_W - TRAY_W) / 12;
  const POINT_H = (H - 2 * BORDER) / 2 - 4;
  const CHECK_R = POINT_W * 0.44;

  const COL_BG = '#2a2d3a';
  const COL_BORDER = '#414868';
  const COL_BAR = '#1f2233';
  const COL_TRAY = '#1f2233';
  const COL_TRI_LIGHT = '#3b4261';
  const COL_TRI_DARK = '#565f89';
  const COL_X = '#7aa2f7';
  const COL_O = '#f7768e';

  // Point label for hovering: 1–24
  function pointLabel(i) { return i + 1; }

  // Compute triangle positions (bottom row: points 1–12, top row: 13–24)
  // Standard right-oriented layout:
  // Bottom (from right to left): points 1..6 | BAR | 7..12
  // Top (from left to right): points 13..18 | BAR | 19..24
  function triX(i) {
    if (i < 6) {
      // Bottom-right: points 1-6 (right of bar)
      return BORDER + 6 * POINT_W + BAR_W + (5 - i) * POINT_W;
    } else if (i < 12) {
      // Bottom-left: points 7-12 (left of bar)
      return BORDER + (11 - i) * POINT_W;
    } else if (i < 18) {
      // Top-left: points 13-18
      return BORDER + (i - 12) * POINT_W;
    } else {
      // Top-right: points 19-24
      return BORDER + 6 * POINT_W + BAR_W + (i - 18) * POINT_W;
    }
  }

  function isBottom(i) { return i < 12; }

  // Generate triangle SVG path
  function triPath(i) {
    const x = triX(i);
    if (isBottom(i)) {
      const y = H - BORDER;
      return `M${x},${y} L${x + POINT_W / 2},${y - POINT_H} L${x + POINT_W},${y} Z`;
    } else {
      const y = BORDER;
      return `M${x},${y} L${x + POINT_W / 2},${y + POINT_H} L${x + POINT_W},${y} Z`;
    }
  }

  function triColor(i) {
    return i % 2 === 0 ? COL_TRI_LIGHT : COL_TRI_DARK;
  }

  // Checker positions
  function checkerCX(pointIdx) {
    return triX(pointIdx) + POINT_W / 2;
  }

  function checkerCY(pointIdx, stackPos) {
    const gap = CHECK_R * 2.0;
    if (isBottom(pointIdx)) {
      return H - BORDER - CHECK_R - stackPos * gap;
    } else {
      return BORDER + CHECK_R + stackPos * gap;
    }
  }

  // Bar checker positions
  function barCX() { return BORDER + 6 * POINT_W + BAR_W / 2; }
  function barCY(player, stackPos) {
    const gap = CHECK_R * 2.0;
    if (player === 0) { // X = bottom
      return H / 2 + CHECK_R + 4 + stackPos * gap;
    } else { // O = top
      return H / 2 - CHECK_R - 4 - stackPos * gap;
    }
  }

  // Tray (borne off)
  const trayX = W - TRAY_W + TRAY_W / 2;

  function trayCY(player, stackPos) {
    const gap = CHECK_R * 0.65;
    if (player === 0) { // X = bottom
      return H - BORDER - 6 - stackPos * gap;
    } else { // O = top
      return BORDER + 6 + stackPos * gap;
    }
  }

  // Cube position
  function cubeCX() {
    if (cubeOwner === 0) return W - TRAY_W / 2; // center → tray
    if (cubeOwner === 1) return W - TRAY_W / 2; // X → bottom tray
    return W - TRAY_W / 2; // O → top tray
  }
  function cubeCY() {
    if (cubeOwner === 0) return H / 2;
    if (cubeOwner === 1) return H / 2 + 50;
    return H / 2 - 50;
  }

  let cubeValue = $derived(1 << cubeLog2);

  // Build checker display data
  let checkers = $derived.by(() => {
    const items = [];
    for (let i = 0; i < 24; i++) {
      const count = board[i];
      if (count === 0) continue;
      const absCount = Math.abs(count);
      const player = count > 0 ? 0 : 1; // 0=X, 1=O
      const color = player === 0 ? COL_X : COL_O;
      const maxShow = 5;
      const visible = Math.min(absCount, maxShow);
      for (let s = 0; s < visible; s++) {
        items.push({
          cx: checkerCX(i),
          cy: checkerCY(i, s),
          color,
          label: s === visible - 1 && absCount > maxShow ? absCount : null,
        });
      }
    }
    // Bar
    for (let s = 0; s < Math.min(barX, 5); s++) {
      items.push({
        cx: barCX(),
        cy: barCY(0, s),
        color: COL_X,
        label: s === Math.min(barX, 5) - 1 && barX > 5 ? barX : null,
      });
    }
    for (let s = 0; s < Math.min(barO, 5); s++) {
      items.push({
        cx: barCX(),
        cy: barCY(1, s),
        color: COL_O,
        label: s === Math.min(barO, 5) - 1 && barO > 5 ? barO : null,
      });
    }
    return items;
  });

  // Borne-off items
  let borneOff = $derived.by(() => {
    const items = [];
    for (let s = 0; s < Math.min(borneOffX, 15); s++) {
      items.push({ cx: trayX, cy: trayCY(0, s), color: COL_X });
    }
    for (let s = 0; s < Math.min(borneOffO, 15); s++) {
      items.push({ cx: trayX, cy: trayCY(1, s), color: COL_O });
    }
    return items;
  });

  // Point numbers
  let pointNumbers = $derived.by(() => {
    const nums = [];
    for (let i = 0; i < 24; i++) {
      nums.push({
        x: triX(i) + POINT_W / 2,
        y: isBottom(i) ? H - 1 : 11,
        label: pointLabel(i),
      });
    }
    return nums;
  });
</script>

<svg viewBox="0 0 {W} {H}" class="board-svg" xmlns="http://www.w3.org/2000/svg">
  <!-- Background -->
  <rect x="0" y="0" width={W} height={H} fill={COL_BG} rx="4" />

  <!-- Board border -->
  <rect x={BORDER} y={BORDER} width={W - 2 * BORDER - TRAY_W} height={H - 2 * BORDER}
    fill="none" stroke={COL_BORDER} stroke-width="1.5" rx="2" />

  <!-- Bar -->
  <rect x={BORDER + 6 * POINT_W} y={BORDER} width={BAR_W} height={H - 2 * BORDER}
    fill={COL_BAR} />

  <!-- Tray -->
  <rect x={W - TRAY_W} y={BORDER} width={TRAY_W - BORDER} height={H - 2 * BORDER}
    fill={COL_TRAY} stroke={COL_BORDER} stroke-width="0.5" rx="2" />

  <!-- Triangles -->
  {#each Array(24) as _, i}
    <path d={triPath(i)} fill={triColor(i)} opacity="0.8" />
  {/each}

  <!-- Point numbers -->
  {#each pointNumbers as pn}
    <text x={pn.x} y={pn.y} text-anchor="middle" fill="#565f89" font-size="7" font-family="monospace">{pn.label}</text>
  {/each}

  <!-- Checkers on points -->
  {#each checkers as c}
    <circle cx={c.cx} cy={c.cy} r={CHECK_R} fill={c.color} stroke="#1a1b26" stroke-width="1" />
    {#if c.label}
      <text x={c.cx} y={c.cy + 3.5} text-anchor="middle" fill="#1a1b26" font-size="10" font-weight="bold">{c.label}</text>
    {/if}
  {/each}

  <!-- Borne off -->
  {#each borneOff as b}
    <rect x={b.cx - CHECK_R * 0.7} y={b.cy - 2.5} width={CHECK_R * 1.4} height={5}
      fill={b.color} rx="1" opacity="0.85" />
  {/each}

  <!-- Cube -->
  {#if cubeLog2 > 0}
    <rect x={cubeCX() - 11} y={cubeCY() - 11} width="22" height="22"
      fill="#e0af68" rx="3" stroke="#1a1b26" stroke-width="1" />
    <text x={cubeCX()} y={cubeCY() + 4.5} text-anchor="middle"
      fill="#1a1b26" font-size="12" font-weight="bold">{cubeValue}</text>
  {/if}

  <!-- Score / on roll indicator -->
  <text x={BORDER + 3} y={H - BORDER + 10} fill={COL_X} font-size="8" font-family="monospace">
    X: {awayX} away {sideToMove === 0 ? '●' : ''}
  </text>
  <text x={BORDER + 3} y={BORDER - 3} fill={COL_O} font-size="8" font-family="monospace">
    O: {awayO} away {sideToMove === 1 ? '●' : ''}
  </text>
</svg>

<style>
  .board-svg {
    width: 100%;
    max-width: 520px;
    height: auto;
    display: block;
  }
</style>
