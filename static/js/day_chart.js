(function () {
  const $ = id => document.getElementById(id);
  const visibility = new Map();
  const root = $('chart');
  const filter = $('driverFilter');
  const all = $('allbtn');
  let charts = [], data, requestId = 0;
  const visible = name => visibility.get(name) !== false;
  const panels = () => $('ctype').value === 'panels';

  function updateAllButton() {
    all.disabled = !data?.series.length;
    all.textContent = data?.series.some(s => visible(s.name)) ? 'Hide all' : 'Show all';
  }

  function options(style, height) {
    return {
      chart: {type: style, height, borderRadius: 0, animation: false},
      title: {text: null}, credits: {enabled: false},
      xAxis: {categories: data.categories, title: {text: data.xTitle || null}},
      yAxis: {title: {text: data.yTitle}, reversed: data.reversed,
        allowDecimals: !(data.yTitle === 'Position' || data.yTitle.startsWith('Laps'))},
      tooltip: {shared: true, crosshairs: true, valueDecimals: 3},
      plotOptions: {series: {connectNulls: true, animation: false}}
    };
  }

  function renderCharts() {
    charts.forEach(chart => chart.destroy());
    charts = [];
    root.replaceChildren();
    root.classList.toggle('chart-panels', panels());
    if (!panels()) {
      const config = options($('ctype').value, 480);
      config.plotOptions.series.events = {
        show() { visibility.set(this.name, true); updateAllButton(); },
        hide() { visibility.set(this.name, false); updateAllButton(); }
      };
      config.series = data.series.map(s => ({...s, data: [...s.data], visible: visible(s.name)}));
      charts.push(Highcharts.chart(root, config));
      return;
    }

    // Keep the same axes across drivers, even when part of the field is hidden.
    let min = Infinity, max = -Infinity;
    for (const series of data.series) {
      for (const value of series.data) {
        if (!Number.isFinite(value)) continue;
        min = Math.min(min, value);
        max = Math.max(max, value);
      }
    }
    const shown = data.series.filter(s => visible(s.name));
    if (!shown.length) {
      const message = document.createElement('p');
      message.textContent = data.series.length ? 'Select a driver to show their chart.' : 'No results for this selection.';
      root.append(message);
      return;
    }
    for (const series of shown) {
      const card = document.createElement('section');
      const heading = document.createElement('h3');
      const plot = document.createElement('div');
      heading.textContent = series.name;
      card.className = 'driver-chart-panel';
      card.append(heading, plot);
      root.append(card);

      const config = options('line', 230);
      config.chart.marginLeft = 66;
      config.legend = {enabled: false};
      if (min < Infinity) {
        const padding = min === max ? Math.max(Math.abs(min) * 0.02, 0.1) : (max - min) * 0.04;
        Object.assign(config.yAxis, {min: min - padding, max: max + padding, tickAmount: 4});
      }
      config.tooltip.shared = false;
      config.plotOptions.series.marker = {enabled: true, radius: 2};
      config.series = [{...series, data: [...series.data]}];
      charts.push(Highcharts.chart(plot, config));
    }
  }

  function render() {
    if (!data) return;
    filter.hidden = !panels() || !data.series.length;
    filter.querySelectorAll('label').forEach(label => label.remove());
    if (!filter.hidden) {
      for (const series of data.series) {
        const label = document.createElement('label');
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.checked = visible(series.name);
        input.addEventListener('change', () => {
          visibility.set(series.name, input.checked);
          renderCharts();
          updateAllButton();
        });
        label.append(input, series.name);
        filter.append(label);
      }
    }
    renderCharts();
    updateAllButton();
  }

  async function load() {
    const id = ++requestId;
    const mode = $('mode').value;
    $('metricBox').hidden = mode === 'laps';
    $('roundBox').hidden = mode !== 'laps';
    const p = new URLSearchParams({class: CHART.cls, mode, metric: $('metric').value, round: $('round').value});
    const result = await (await fetch(CHART.url + '?' + p)).json();
    if (id !== requestId) return;
    data = result;
    render();
  }

  ['mode', 'metric', 'round'].forEach(i => $(i).addEventListener('change', load));
  $('ctype').addEventListener('change', render);
  all.addEventListener('click', () => {
    const show = !data.series.some(s => visible(s.name));
    data.series.forEach(s => visibility.set(s.name, show));
    if (panels()) {
      render();
    } else {
      charts[0].series.forEach(s => s.setVisible(show, false));
      charts[0].redraw();
      updateAllButton();
    }
  });
  load();
})();
