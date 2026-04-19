<script>
  /**
   * BE.7 — MwcChart
   * ECharts line chart: MWC vs move index across the full match.
   * Game boundaries as dashed verticals, Crawford/PCR shaded bands.
   * Hover syncs with TrajectoryCanvas via onHover / hoveredMoveIndex.
   */
  import { onMount, onDestroy } from 'svelte';
  import * as echarts from 'echarts';

  // ── Props ──────────────────────────────────────────────────────────────────

  let {
    match            = null,
    pov              = 'p1',
    hoveredMoveIndex = null,
    onHover          = null,   // (index | null) => void
  } = $props();

  // ── State ──────────────────────────────────────────────────────────────────

  let container;
  let chart;

  // ── Helpers ────────────────────────────────────────────────────────────────

  const RDBU = [
    [103,0,31],[178,24,43],[214,96,77],[244,165,130],[253,219,199],
    [247,247,247],[209,229,240],[146,197,222],[67,147,195],[33,102,172],[5,48,97],
  ];
  function rdbuHex(t) {
    const s = Math.max(0, Math.min(1, t)) * (RDBU.length - 1);
    const lo = Math.floor(s), hi = Math.min(lo + 1, RDBU.length - 1);
    const f = s - lo;
    const r = Math.round(RDBU[lo][0] + f * (RDBU[hi][0] - RDBU[lo][0]));
    const g = Math.round(RDBU[lo][1] + f * (RDBU[hi][1] - RDBU[lo][1]));
    const b = Math.round(RDBU[lo][2] + f * (RDBU[hi][2] - RDBU[lo][2]));
    return `rgb(${r},${g},${b})`;
  }

  function buildOption(positions, pv) {
    if (!positions?.length) return {};

    const mwcValues = positions.map(p =>
      pv === 'p1' ? (p.mwc_p1 ?? 0.5) : 1 - (p.mwc_p1 ?? 0.5)
    );

    // Detect game boundaries (indices where game_number changes)
    const boundaries = [];
    for (let i = 1; i < positions.length; i++) {
      if (positions[i].game_number !== positions[i - 1].game_number) {
        boundaries.push(i);
      }
    }

    // Build markLine data for game boundaries
    const markLineData = boundaries.map(idx => ({
      xAxis: idx,
      lineStyle: { type: 'dashed', color: 'rgba(255,255,255,0.3)', width: 1 },
      label: { show: false },
    }));

    // Build markArea data for Crawford / Post-Crawford spans
    const markAreaData = [];
    let spanStart = null;
    let spanType = null;
    for (let i = 0; i < positions.length; i++) {
      const p = positions[i];
      const type = p.crawford === true ? 'crawford'
                 : p.is_post_crawford === true ? 'post_crawford'
                 : null;
      if (type !== spanType) {
        if (spanStart !== null && spanType !== null) {
          markAreaData.push([
            { xAxis: spanStart, itemStyle: { color: spanType === 'crawford'
              ? 'rgba(255,230,100,0.07)' : 'rgba(255,170,50,0.07)' } },
            { xAxis: i - 1 },
          ]);
        }
        spanStart = i;
        spanType = type;
      }
    }
    if (spanStart !== null && spanType !== null) {
      markAreaData.push([
        { xAxis: spanStart, itemStyle: { color: spanType === 'crawford'
          ? 'rgba(255,230,100,0.07)' : 'rgba(255,170,50,0.07)' } },
        { xAxis: positions.length - 1 },
      ]);
    }

    // Data: [index, mwc, color]
    const seriesData = mwcValues.map((v, i) => ({
      value: [i, v],
      itemStyle: { color: rdbuHex(v) },
    }));

    return {
      backgroundColor: '#1a1b26',
      animation: false,
      grid: { top: 12, right: 12, bottom: 32, left: 44 },
      xAxis: {
        type: 'value',
        min: 0,
        max: positions.length - 1,
        axisLabel: { color: '#565f89', fontSize: 10 },
        axisLine: { lineStyle: { color: '#3b4261' } },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 1,
        axisLabel: { color: '#565f89', fontSize: 10,
          formatter: v => v.toFixed(1) },
        axisLine: { lineStyle: { color: '#3b4261' } },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross', lineStyle: { color: 'rgba(255,255,255,0.3)' } },
        backgroundColor: '#24283b',
        borderColor: '#3b4261',
        textStyle: { color: '#c0caf5', fontSize: 11 },
        formatter(params) {
          const idx = params[0]?.axisValue;
          const p = positions[idx];
          if (!p) return '';
          const mwc = pv === 'p1' ? (p.mwc_p1 ?? 0.5) : 1 - (p.mwc_p1 ?? 0.5);
          const err = p.move_played_error ?? 0;
          return [
            `#${p.move_number} · G${p.game_number}`,
            `MWC ${mwc.toFixed(3)}`,
            err > 0.001 ? `err ${err.toFixed(3)}` : null,
          ].filter(Boolean).join(' · ');
        },
      },
      series: [{
        type: 'line',
        data: seriesData,
        lineStyle: { color: '#7aa2f7', width: 1.5 },
        symbol: 'circle',
        symbolSize: 4,
        markLine: {
          silent: true,
          symbol: 'none',
          data: markLineData,
        },
        markArea: markAreaData.length ? {
          silent: true,
          data: markAreaData,
        } : undefined,
      }],
    };
  }

  // ── Lifecycle ──────────────────────────────────────────────────────────────

  onMount(() => {
    chart = echarts.init(container, 'dark', { renderer: 'canvas' });

    chart.on('mousemove', params => {
      if (params.componentType === 'series' && params.dataIndex != null) {
        onHover?.(params.dataIndex);
      }
    });
    chart.on('mouseout', () => onHover?.(null));

    const ro = new ResizeObserver(() => chart?.resize());
    ro.observe(container);
    return () => { ro.disconnect(); chart?.dispose(); };
  });

  onDestroy(() => { chart?.dispose(); chart = null; });

  // Update chart when match / pov changes
  $effect(() => {
    const positions = match?.positions ?? [];
    if (chart) chart.setOption(buildOption(positions, pov), true);
  });

  // Sync external hover → chart highlight
  $effect(() => {
    if (!chart) return;
    if (hoveredMoveIndex != null) {
      chart.dispatchAction({ type: 'highlight', seriesIndex: 0, dataIndex: hoveredMoveIndex });
    } else {
      chart.dispatchAction({ type: 'downplay', seriesIndex: 0 });
    }
  });
</script>

<div bind:this={container} style="width:100%;height:100%;"></div>
