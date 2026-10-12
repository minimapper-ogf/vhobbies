(function () {
  const $ = id => document.getElementById(id);
  let chart, hidden = false;
  async function load() {
    const mode = $('mode').value;
    $('metricBox').hidden = mode === 'laps'; $('roundBox').hidden = mode !== 'laps';
    const p = new URLSearchParams({class: CHART.cls, mode, metric: $('metric').value, round: $('round').value});
    const d = await (await fetch('/api/day/' + CHART.day + '/chart?' + p)).json();
    chart = Highcharts.chart('chart', {
      chart: {type: $('ctype').value, height: 480, borderRadius: 0, animation: false},
      title: {text: null}, credits: {enabled: false},
      xAxis: {categories: d.categories, title: {text: d.xTitle || null}},
      yAxis: {title: {text: d.yTitle}, reversed: d.reversed, allowDecimals: !(d.yTitle === 'Position' || d.yTitle.startsWith('Laps'))},
      tooltip: {shared: false, valueDecimals: 3},
      plotOptions: {series: {connectNulls: true, animation: false}},
      series: d.series
    });
    hidden = false; $('allbtn').textContent = 'Hide all';
  }
  ['mode', 'metric', 'round', 'ctype'].forEach(i => $(i).addEventListener('change', load));
  $('allbtn').addEventListener('click', () => {
    hidden = !hidden; chart.series.forEach(s => s.setVisible(!hidden, false)); chart.redraw();
    $('allbtn').textContent = hidden ? 'Show all' : 'Hide all';
  });
  load();
})();
