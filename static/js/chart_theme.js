// Force a light chart no matter what the visitor's system/browser theme is.
Highcharts.setOptions({
  chart: {backgroundColor: '#ffffff', style: {color: '#1d221a'}},
  title: {style: {color: '#1d221a'}},
  xAxis: {labels: {style: {color: '#444'}}, title: {style: {color: '#444'}}, lineColor: '#ccd1c2', tickColor: '#ccd1c2', gridLineColor: '#e6e9de'},
  yAxis: {labels: {style: {color: '#444'}}, title: {style: {color: '#444'}}, lineColor: '#ccd1c2', gridLineColor: '#e6e9de'},
  legend: {itemStyle: {color: '#1d221a'}, itemHoverStyle: {color: '#000'}, itemHiddenStyle: {color: '#aaa'}},
  tooltip: {backgroundColor: '#ffffff', style: {color: '#1d221a'}},
  credits: {enabled: false}
});
