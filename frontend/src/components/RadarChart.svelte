<!--
  RadarChart.svelte — LayerCake-style SVG radar for player profiles.
  Props: data ({ axis, value, compare? }[]), maxValue
-->
<script lang="ts">
  let {
    data    = [] as Array<{ axis: string; value: number; compare?: number }>,
    maxVal  = 0.15,
    size    = 220,
  } = $props();

  const cx     = size / 2;
  const cy     = size / 2;
  const radius = size / 2 - 30;
  const levels = 4;

  function angleFor(i: number, n: number) {
    return (Math.PI * 2 * i) / n - Math.PI / 2;
  }

  function toXY(val: number, i: number, n: number) {
    const r = (val / maxVal) * radius;
    const a = angleFor(i, n);
    return { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) };
  }

  function polygon(values: number[]) {
    return values
      .map((v, i) => { const p = toXY(v, i, values.length); return `${p.x},${p.y}`; })
      .join(' ');
  }

  let n       = $derived(data.length);
  let values  = $derived(data.map(d => d.value));
  let compVals = $derived(data.map(d => d.compare ?? 0));
  let hasComp  = $derived(data.some(d => d.compare !== undefined));
</script>

<svg viewBox="0 0 {size} {size}" style="width:100%;max-width:{size}px;height:auto;">
  <!-- Grid rings -->
  {#each Array.from({length: levels}, (_, i) => (i + 1) / levels) as f}
    <polygon
      points={polygon(Array(n).fill(f * maxVal))}
      fill="none" stroke="#3a2010" stroke-width="1"
    />
  {/each}

  <!-- Axes -->
  {#each data as _, i}
    {@const tip = toXY(maxVal, i, n)}
    <line x1={cx} y1={cy} x2={tip.x} y2={tip.y} stroke="#3a2010" stroke-width="1"/>
    <!-- Label -->
    {@const lp = toXY(maxVal * 1.18, i, n)}
    <text x={lp.x} y={lp.y} text-anchor="middle" dominant-baseline="central"
          font-size="8" fill="#907060">{data[i].axis}</text>
  {/each}

  <!-- Compare polygon -->
  {#if hasComp}
    <polygon points={polygon(compVals)} fill="#4040c020" stroke="#4040c0" stroke-width="1.5" stroke-dasharray="3,2"/>
  {/if}

  <!-- Player polygon -->
  <polygon points={polygon(values)} fill="#d4a83530" stroke="#d4a835" stroke-width="2"/>

  <!-- Dots -->
  {#each data as d, i}
    {@const p = toXY(d.value, i, n)}
    <circle cx={p.x} cy={p.y} r="3.5" fill="#d4a835"/>
  {/each}
</svg>
