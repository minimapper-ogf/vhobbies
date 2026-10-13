(function () {
  const $ = id => document.getElementById(id);
  let chart, hidden = false;
  async function load() {
    const visibility = Object.fromEntries((chart ? chart.series : []).map(s => [s.name, s.visible]));
    const mode = $('mode').value;
    $('metricBox').hidden = mode === 'laps'; $('roundBox').hidden = mode !== 'laps';
    const p = new URLSearchParams({class: CHART.cls, mode, metric: $('metric').value, round: $('round').value});
    const d = await (await fetch('/api/day/' + CHART.day + '/chart?' + p)).json();
    chart = Highcharts.chart('chart', {
      chart: {type: $('ctype').value, height: 480, borderRadius: 0, animation: false},
      title: {text: null}, credits: {enabled: false},
      xAxis: {categories: d.categories, title: {text: d.xTitle || null}},
      yAxis: {title: {text: d.yTitle}, reversed: d.reversed, allowDecimals: !(d.yTitle === 'Position' || d.yTitle.startsWith('Laps'))},
      tooltip: {shared: true, crosshairs: true, valueDecimals: 3},
      plotOptions: {series: {connectNulls: true, animation: false}},
      series: d.series.map(s => ({...s, visible: Object.prototype.hasOwnProperty.call(visibility, s.name) ? visibility[s.name] : true}))
    });
    hidden = chart.series.length > 0 && chart.series.every(s => !s.visible);
    $('allbtn').textContent = hidden ? 'Show all' : 'Hide all';
  }
  ['mode', 'metric', 'round', 'ctype'].forEach(i => $(i).addEventListener('change', load));
  $('allbtn').addEventListener('click', () => {
    hidden = !hidden; chart.series.forEach(s => s.setVisible(!hidden, false)); chart.redraw();
    $('allbtn').textContent = hidden ? 'Show all' : 'Hide all';
  });
  load();
})();
