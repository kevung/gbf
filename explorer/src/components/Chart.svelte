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
      chart.on('click', (params) => {
        if (params.data) onPointClick(params);
      });
    }

    const ro = new ResizeObserver(() => chart?.resize());
    ro.observe(container);

    return () => {
      ro.disconnect();
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

<div bind:this={container} style="width:100%; height:{height}; background:var(--bg); border:1px solid var(--border); border-radius:var(--radius);"></div>
