<script>
  import { onMount, onDestroy } from 'svelte';
  import * as echarts from 'echarts';

  let { option = {}, height = '500px', onPointClick = null } = $props();

  let container;
  let chart;

  onMount(() => {
    chart = echarts.init(container, 'dark', { renderer: 'canvas' });
    chart.setOption(option);

    if (onPointClick) {
      // Direct click on a data point
      chart.on('click', (params) => {
        if (params.data) onPointClick(params);
      });

      // Nearest-point fallback: click on blank area finds the closest point
      chart.getZr().on('click', (e) => {
        // Only fire if ECharts didn't already handle a data-point click
        if (e.target) return;
        const pointInPixel = [e.offsetX, e.offsetY];
        if (!chart.containPixel('grid', pointInPixel)) return;

        // Find the nearest data point across all scatter series
        let bestDist = Infinity;
        let bestParams = null;
        const opt = chart.getOption();
        const series = opt.series || [];
        for (let si = 0; si < series.length; si++) {
          const s = series[si];
          if (s.type !== 'scatter') continue;
          const data = s.data || [];
          for (let di = 0; di < data.length; di++) {
            const d = data[di];
            const px = chart.convertToPixel({ seriesIndex: si }, [d[0], d[1]]);
            if (!px) continue;
            const dx = px[0] - e.offsetX;
            const dy = px[1] - e.offsetY;
            const dist = dx * dx + dy * dy;
            if (dist < bestDist) {
              bestDist = dist;
              bestParams = { data: d, seriesIndex: si, dataIndex: di, name: s.name };
            }
          }
        }
        // Accept if within 20px radius
        if (bestParams && bestDist < 400) {
          onPointClick(bestParams);
        }
      });
    }

    const ro = new ResizeObserver(() => chart?.resize());
    ro.observe(container);

    // Handle visibility changes (CSS display:none tabs).
    const io = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting && chart) {
          chart.resize();
        }
      }
    });
    io.observe(container);

    return () => {
      ro.disconnect();
      io.disconnect();
      chart?.dispose();
    };
  });

  onDestroy(() => {
    chart?.dispose();
    chart = null;
  });

  $effect(() => {
    if (chart && option) {
      chart.setOption(option, true);
    }
  });
</script>

<div bind:this={container} style="width:100%; height:{height}; background:var(--bg); border:1px solid var(--border); border-radius:var(--radius); cursor:crosshair;"></div>
