<!--
  Board.svelte — S4.3 Backgammon board visualization component.

  Input format (board prop):
    board[0]    : p1 checkers on bar  (positive integer)
    board[1..24]: point occupancy (positive = p1, negative = p2)
    board[25]   : p2 checkers on bar  (positive integer)

  Player 1 moves 24 → 1 (home board: points 1–6).
  Player 2 moves 1 → 24 (home board: points 19–24).
-->
<script lang="ts">
  // ── Props ──────────────────────────────────────────────────────────────────
  let {
    board       = Array(26).fill(0) as number[],
    cube_value  = 1,
    cube_owner  = 0 as 0 | 1 | 2,   // 0 = centred, 1 = p1, 2 = p2
    away_p1     = 7,
    away_p2     = 7,
    dice        = null as [number, number] | null,
    moves       = [] as Array<[number, number]>,
    p1_color    = '#f0d9b5',         // cream
    p2_color    = '#1a0a00',         // very dark brown
    flip        = false,             // swap top/bottom perspective
  } = $props();

  // ── Geometry ───────────────────────────────────────────────────────────────
  const VW        = 800;   // viewBox width
  const VH        = 520;   // viewBox height
  const MARGIN    = 14;
  const PT_W      = 54;    // point (triangle) width
  const PT_H      = 195;   // triangle height (half board height)
  const BAR_W     = 40;
  const CR        = 20;    // checker radius
  const BEAR_W    = 52;    // bear-off strip width

  // Derived x anchors
  const LEFT_X  = MARGIN;                       // left edge of left section
  const BAR_X   = LEFT_X + 6 * PT_W;           // left edge of bar
  const RIGHT_X = BAR_X + BAR_W;               // left edge of right section
  const BEAR_X  = RIGHT_X + 6 * PT_W + MARGIN; // bear-off strip x
  const BOARD_W = BEAR_X + BEAR_W + MARGIN;    // total board width (≈800)

  const BOARD_TOP    = MARGIN;
  const BOARD_BOTTOM = VH - MARGIN;
  const MID_Y        = VH / 2;

  // ── Point geometry ─────────────────────────────────────────────────────────
  // Standard layout (flip=false):
  //   Top row (left→right):    13 14 15 16 17 18 | 19 20 21 22 23 24
  //   Bottom row (left→right): 12 11 10  9  8  7 |  6  5  4  3  2  1

  function ptCenterX(pt: number): number {
    let idx: number; // 0-based position within its half-row
    if (pt >= 1 && pt <= 6)   idx = 6 - pt;           // right section, bottom
    else if (pt >= 7 && pt <= 12)  idx = 12 - pt;     // left section, bottom
    else if (pt >= 13 && pt <= 18) idx = pt - 13;     // left section, top
    else                           idx = pt - 19;     // right section, top

    const section_x = (pt <= 12)
      ? (pt <= 6  ? RIGHT_X : LEFT_X)
      : (pt <= 18 ? LEFT_X  : RIGHT_X);

    return section_x + idx * PT_W + PT_W / 2;
  }

  function ptIsTop(pt: number): boolean {
    const top = pt >= 13 && pt <= 24;
    return flip ? !top : top;
  }

  function trianglePoints(pt: number): string {
    const cx  = ptCenterX(pt);
    const top = ptIsTop(pt);
    const x1  = cx - PT_W / 2 + 1;
    const x2  = cx + PT_W / 2 - 1;
    const base_y = top ? BOARD_TOP  : BOARD_BOTTOM;
    const tip_y  = top ? BOARD_TOP + PT_H : BOARD_BOTTOM - PT_H;
    return `${x1},${base_y} ${x2},${base_y} ${cx},${tip_y}`;
  }

  // Point colours: odd points (1,3,5…) = dark, even = light
  function ptFill(pt: number): string {
    return pt % 2 === 1 ? '#8b2020' : '#d4a835';
  }

  // ── Checker stacking ───────────────────────────────────────────────────────
  interface Checker {
    x: number; y: number;
    player: 1 | 2;
    label: string | null; // overflow count label
  }

  function stackCheckers(pt: number, count: number, player: 1 | 2): Checker[] {
    const cx  = ptCenterX(pt);
    const top = ptIsTop(pt);
    const visible = Math.min(count, 5);
    const result: Checker[] = [];
    for (let i = 0; i < visible; i++) {
      const step = CR * 1.85;
      const cy   = top
        ? BOARD_TOP  + CR + i * step
        : BOARD_BOTTOM - CR - i * step;
      result.push({
        x: cx, y: cy, player,
        label: i === 4 && count > 5 ? String(count) : null,
      });
    }
    return result;
  }

  // Bar checker y positions
  function barCheckerY(player: 1 | 2, idx: number): number {
    const step = CR * 1.85;
    if (player === 1) {
      // p1 bar: bottom half
      return MID_Y + CR * 1.5 + idx * step;
    } else {
      // p2 bar: top half
      return MID_Y - CR * 1.5 - idx * step;
    }
  }

  // Bear-off checker y positions (stacked vertically in strip)
  function bearY(player: 1 | 2, idx: number): number {
    if (player === 1) {
      return BOARD_BOTTOM - CR - idx * (CR * 1.7);
    } else {
      return BOARD_TOP + CR + idx * (CR * 1.7);
    }
  }

  // ── Computed lists ─────────────────────────────────────────────────────────
  function allCheckers(): Checker[] {
    const result: Checker[] = [];
    for (let pt = 1; pt <= 24; pt++) {
      const v = board[pt] ?? 0;
      if (v === 0) continue;
      const player: 1 | 2 = v > 0 ? 1 : 2;
      result.push(...stackCheckers(pt, Math.abs(v), player));
    }
    // Bar
    const p1b = board[0]  ?? 0;
    const p2b = board[25] ?? 0;
    const barX = BAR_X + BAR_W / 2;
    for (let i = 0; i < Math.min(p1b, 3); i++)
      result.push({ x: barX, y: barCheckerY(1, i), player: 1,
        label: i === 2 && p1b > 3 ? String(p1b) : null });
    for (let i = 0; i < Math.min(p2b, 3); i++)
      result.push({ x: barX, y: barCheckerY(2, i), player: 2,
        label: i === 2 && p2b > 3 ? String(p2b) : null });
    return result;
  }

  // Bear-off counts (inferred: 15 - checkers on board - bar)
  function bearOff(player: 1 | 2): number {
    let on_board = 0;
    for (let pt = 1; pt <= 24; pt++) {
      const v = board[pt] ?? 0;
      if (player === 1 && v > 0) on_board += v;
      if (player === 2 && v < 0) on_board += -v;
    }
    const bar = player === 1 ? (board[0] ?? 0) : (board[25] ?? 0);
    return 15 - on_board - bar;
  }

  function bearOffCheckers(player: 1 | 2): Checker[] {
    const count = bearOff(player);
    const bx    = BEAR_X + BEAR_W / 2;
    const result: Checker[] = [];
    for (let i = 0; i < Math.min(count, 8); i++) {
      result.push({ x: bx, y: bearY(player, i), player,
        label: i === 7 && count > 8 ? String(count) : null });
    }
    return result;
  }

  // ── Move arrows ────────────────────────────────────────────────────────────
  function arrowPath(from: number, to: number): string {
    const x1 = from === 0 || from === 25 ? BAR_X + BAR_W / 2 : ptCenterX(from);
    const x2 = to   === 0 || to   === 25 ? BAR_X + BAR_W / 2 : ptCenterX(to);
    const y1 = ptIsTop(from) ? BOARD_TOP + PT_H * 0.6 : BOARD_BOTTOM - PT_H * 0.6;
    const y2 = ptIsTop(to)   ? BOARD_TOP + PT_H * 0.6 : BOARD_BOTTOM - PT_H * 0.6;
    // Quadratic curve
    const mx  = (x1 + x2) / 2;
    const my  = (y1 + y2) / 2 - 30;
    return `M ${x1} ${y1} Q ${mx} ${my} ${x2} ${y2}`;
  }

  // ── Dice rendering ─────────────────────────────────────────────────────────
  const DIE_PIPS: Record<number, [number, number][]> = {
    1: [[0.5, 0.5]],
    2: [[0.2, 0.2], [0.8, 0.8]],
    3: [[0.2, 0.2], [0.5, 0.5], [0.8, 0.8]],
    4: [[0.2, 0.2], [0.8, 0.2], [0.2, 0.8], [0.8, 0.8]],
    5: [[0.2, 0.2], [0.8, 0.2], [0.5, 0.5], [0.2, 0.8], [0.8, 0.8]],
    6: [[0.2, 0.2], [0.8, 0.2], [0.2, 0.5], [0.8, 0.5], [0.2, 0.8], [0.8, 0.8]],
  };

  // ── Cube position ──────────────────────────────────────────────────────────
  function cubeXY(): { x: number; y: number } {
    const cx = BAR_X + BAR_W / 2;
    if (cube_owner === 0) return { x: cx, y: MID_Y };
    if (cube_owner === 1) return { x: cx, y: BOARD_BOTTOM - 36 };
    return { x: cx, y: BOARD_TOP + 36 };
  }

  // ── Reactive ───────────────────────────────────────────────────────────────
  let checkers    = $derived(allCheckers());
  let bearP1      = $derived(bearOffCheckers(1));
  let bearP2      = $derived(bearOffCheckers(2));
  let cubePos     = $derived(cubeXY());
</script>

<!-- ── SVG ──────────────────────────────────────────────────────────────── -->
<svg
  viewBox="0 0 {VW} {VH}"
  xmlns="http://www.w3.org/2000/svg"
  role="img"
  aria-label="Backgammon board"
  style="width:100%;height:auto;display:block;"
>
  <defs>
    <!-- Arrowhead marker for move arrows -->
    <marker id="arrowhead" markerWidth="6" markerHeight="6"
            refX="5" refY="3" orient="auto">
      <path d="M0,0 L6,3 L0,6 Z" fill="#00bfff" opacity="0.9"/>
    </marker>
    <!-- Checker gradients -->
    <radialGradient id="grad_p1" cx="38%" cy="35%">
      <stop offset="0%"   stop-color="#fff8ee"/>
      <stop offset="100%" stop-color="{p1_color}"/>
    </radialGradient>
    <radialGradient id="grad_p2" cx="38%" cy="35%">
      <stop offset="0%"   stop-color="#5a3520"/>
      <stop offset="100%" stop-color="{p2_color}"/>
    </radialGradient>
  </defs>

  <!-- ── Board background ── -->
  <rect x="0" y="0" width={VW} height={VH} fill="#2e1a0e" rx="8"/>
  <!-- Playing area (excluding bear-off) -->
  <rect x={LEFT_X} y={BOARD_TOP} width={BEAR_X - LEFT_X} height={VH - 2 * MARGIN}
        fill="#3d220f" rx="4"/>
  <!-- Bear-off strip -->
  <rect x={BEAR_X} y={BOARD_TOP} width={BEAR_W} height={VH - 2 * MARGIN}
        fill="#2a1508" rx="4" stroke="#5a3a1a" stroke-width="1"/>

  <!-- ── Point triangles ── -->
  {#each Array.from({length: 24}, (_, i) => i + 1) as pt}
    <polygon
      points={trianglePoints(pt)}
      fill={ptFill(pt)}
      opacity="0.82"
    />
  {/each}

  <!-- ── Point numbers (small, at board edges) ── -->
  {#each Array.from({length: 24}, (_, i) => i + 1) as pt}
    <text
      x={ptCenterX(pt)}
      y={ptIsTop(pt) ? BOARD_TOP + PT_H + 14 : BOARD_BOTTOM - PT_H - 4}
      text-anchor="middle"
      font-size="10"
      fill="#a08060"
      font-family="monospace"
    >{pt}</text>
  {/each}

  <!-- ── Bar ── -->
  <rect x={BAR_X} y={BOARD_TOP} width={BAR_W} height={VH - 2 * MARGIN}
        fill="#1e0f05" stroke="#5a3a1a" stroke-width="1"/>
  <!-- Bar label -->
  <text x={BAR_X + BAR_W / 2} y={MID_Y} text-anchor="middle"
        font-size="9" fill="#6a4a2a" font-family="monospace"
        dominant-baseline="middle">BAR</text>

  <!-- ── Centre line ── -->
  <line x1={LEFT_X} y1={MID_Y} x2={BEAR_X} y2={MID_Y}
        stroke="#1e0f05" stroke-width="2"/>

  <!-- ── Move arrows ── -->
  {#each moves as [from, to]}
    <path
      d={arrowPath(from, to)}
      fill="none"
      stroke="#00bfff"
      stroke-width="2.5"
      stroke-linecap="round"
      opacity="0.85"
      marker-end="url(#arrowhead)"
    />
  {/each}

  <!-- ── Checkers ── -->
  {#each checkers as c}
    <circle
      cx={c.x} cy={c.y} r={CR}
      fill={c.player === 1 ? 'url(#grad_p1)' : 'url(#grad_p2)'}
      stroke={c.player === 1 ? '#c8a060' : '#7a4020'}
      stroke-width="1.5"
    />
    {#if c.label}
      <text x={c.x} y={c.y} text-anchor="middle" dominant-baseline="central"
            font-size="11" font-weight="bold"
            fill={c.player === 1 ? '#3a1a00' : '#f0c080'}
            font-family="sans-serif"
      >{c.label}</text>
    {/if}
  {/each}

  <!-- ── Bear-off checkers ── -->
  {#each [...bearP1, ...bearP2] as c}
    <circle
      cx={c.x} cy={c.y} r={CR - 3}
      fill={c.player === 1 ? 'url(#grad_p1)' : 'url(#grad_p2)'}
      stroke={c.player === 1 ? '#c8a060' : '#7a4020'}
      stroke-width="1"
      opacity="0.9"
    />
    {#if c.label}
      <text x={c.x} y={c.y} text-anchor="middle" dominant-baseline="central"
            font-size="10" font-weight="bold"
            fill={c.player === 1 ? '#3a1a00' : '#f0c080'}
            font-family="sans-serif"
      >{c.label}</text>
    {/if}
  {/each}

  <!-- ── Cube ── -->
  <g transform="translate({cubePos.x},{cubePos.y})">
    <rect x="-18" y="-18" width="36" height="36" rx="5"
          fill="#f5f0e0" stroke="#888" stroke-width="1.5"/>
    <text x="0" y="1" text-anchor="middle" dominant-baseline="central"
          font-size="16" font-weight="bold" fill="#222"
          font-family="sans-serif">{cube_value}</text>
  </g>

  <!-- ── Dice ── -->
  {#if dice}
    {#each dice as die, di}
      {@const dx = RIGHT_X + 6 * PT_W - 90 + di * 50}
      {@const dy = MID_Y - 18}
      <rect x={dx} y={dy} width="36" height="36" rx="5"
            fill="#f8f5e8" stroke="#888" stroke-width="1.5"/>
      {#each DIE_PIPS[die] ?? [] as [px, py]}
        <circle cx={dx + px * 36} cy={dy + py * 36} r="3.5" fill="#222"/>
      {/each}
    {/each}
  {/if}

  <!-- ── Away scores ── -->
  <!-- P1 score (bottom-left) -->
  <rect x="4" y={BOARD_BOTTOM - 28} width="60" height="22" rx="4" fill="#1a0a00" opacity="0.7"/>
  <text x="34" y={BOARD_BOTTOM - 14} text-anchor="middle"
        font-size="12" fill={p1_color} font-family="sans-serif">
    P1 – {away_p1}pt
  </text>
  <!-- P2 score (top-left) -->
  <rect x="4" y={BOARD_TOP + 6} width="60" height="22" rx="4" fill="#1a0a00" opacity="0.7"/>
  <text x="34" y={BOARD_TOP + 20} text-anchor="middle"
        font-size="12" fill={p2_color === '#1a0a00' ? '#f0c080' : p2_color}
        font-family="sans-serif">
    P2 – {away_p2}pt
  </text>
</svg>
