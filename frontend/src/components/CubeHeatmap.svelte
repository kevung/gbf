<!--
  CubeHeatmap.svelte — D3-rendered 15×15 cube error heatmap.
  Props: cells (HeatmapCell[]), metric, onCellClick
-->
<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import * as d3 from 'd3';
  import type { HeatmapCell } from '$lib/api';

  let {
    cells       = [] as HeatmapCell[],
    metric      = 'avg_error' as keyof HeatmapCell,
    onCellClick = (_c: HeatmapCell) => {},
  } = $props();

  let svgEl = $state<SVGSVGElement | undefined>(undefined);

  const CELL  = 36;
  const PAD   = 28;
  const MAX_PT = 15;
  const W = CELL * MAX_PT + PAD;
  const H = CELL * MAX_PT + PAD;

  const colorScale = d3.scaleSequential(d3.interpolateYlOrRd).domain([0, 0.12]);

  function draw() {
    if (!svgEl || cells.length === 0) return;
    const svg = d3.select(svgEl);
    svg.selectAll('*').remove();

    const map = new Map(cells.map(c => [`${c.away_p1}_${c.away_p2}`, c]));

    // Axis labels
    for (let i = 1; i <= MAX_PT; i++) {
      svg.append('text').attr('x', PAD + (i - 1) * CELL + CELL / 2).attr('y', 14)
         .attr('text-anchor', 'middle').attr('font-size', 9).attr('fill', '#907060').text(i);
      svg.append('text').attr('x', 12).attr('y', PAD + (i - 1) * CELL + CELL / 2 + 4)
         .attr('text-anchor', 'middle').attr('font-size', 9).attr('fill', '#907060').text(i);
    }

    // Cells
    for (let p1 = 1; p1 <= MAX_PT; p1++) {
      for (let p2 = 1; p2 <= MAX_PT; p2++) {
        const cell = map.get(`${p1}_${p2}`);
        const val  = cell ? (cell[metric] as number) : null;
        const x = PAD + (p1 - 1) * CELL;
        const y = PAD + (p2 - 1) * CELL;

        const rect = svg.append('rect')
          .attr('x', x).attr('y', y)
          .attr('width', CELL - 1).attr('height', CELL - 1)
          .attr('rx', 2)
          .attr('fill', val != null ? colorScale(val) : '#1a0f07')
          .attr('stroke', 'none')
          .style('cursor', cell ? 'pointer' : 'default');

        if (cell) {
          rect.on('click', () => onCellClick(cell))
              .on('mouseover', function() { d3.select(this).attr('stroke', '#f0c060').attr('stroke-width', 1.5); })
              .on('mouseout',  function() { d3.select(this).attr('stroke', 'none'); });

          if (CELL >= 30) {
            svg.append('text')
               .attr('x', x + CELL / 2).attr('y', y + CELL / 2 + 3)
               .attr('text-anchor', 'middle').attr('font-size', 8)
               .attr('fill', val! > 0.06 ? '#fff' : '#333')
               .attr('pointer-events', 'none')
               .text(val!.toFixed(3));
          }
        }
      }
    }
  }

  $effect(() => { cells; metric; draw(); });
  onMount(draw);
</script>

<svg bind:this={svgEl} viewBox="0 0 {W} {H}" style="width:100%;max-width:{W}px;height:auto;">
  <text x={W / 2} y={H - 4} text-anchor="middle" font-size="9" fill="#907060">Away P1 →</text>
</svg>
