'use strict';

for (const form of document.querySelectorAll('form[data-confirm]')) {
  form.addEventListener('submit', (event) => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
}

const typeSelect = document.getElementById('movement_type');
if (typeSelect) {
  const filterOptions = () => {
    for (const select of document.querySelectorAll('#category_id, #site_id')) {
      for (const option of select.options) {
        const incompatible = option.dataset.type !== undefined && option.dataset.type !== typeSelect.value;
        option.hidden = incompatible;
        option.disabled = incompatible;
        if (incompatible && option.selected) select.value = '';
      }
    }
  };
  typeSelect.addEventListener('change', filterOptions);
  filterOptions();
}

async function drawCharts() {
  const container = document.getElementById('charts');
  if (!container) return;
  const status = document.getElementById('chart-status');
  if (typeof Chart === 'undefined') {
    status.textContent = 'No se ha podido cargar la biblioteca de gráficas. Puedes consultar las tablas de datos.';
    return;
  }
  try {
    const response = await fetch(`/api/summary?month=${encodeURIComponent(container.dataset.month)}`, {
      headers: { Accept: 'application/json' }, credentials: 'same-origin',
    });
    if (!response.ok || response.redirected) throw new Error('Summary unavailable');
    const summary = await response.json();
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const money = new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'EUR' });
    const monthLabels = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];
    const monthly = new Map(summary.monthly.map((row) => [Number(row.month.slice(5)), row]));
    Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
    Chart.defaults.color = '#647572';
    new Chart(document.getElementById('evolution-chart'), {
      type: 'bar',
      data: { labels: monthLabels, datasets: [
        { label: 'Ingresos', data: monthLabels.map((_, index) => (monthly.get(index + 1)?.income || 0) / 100), backgroundColor: '#277565', borderRadius: 4 },
        { label: 'Gastos', data: monthLabels.map((_, index) => (monthly.get(index + 1)?.expense || 0) / 100), backgroundColor: '#c6d9cf', borderRadius: 4 },
      ] },
      options: { responsive: true, maintainAspectRatio: false, animation: reducedMotion ? false : undefined,
        plugins: { legend: { position: 'bottom' }, tooltip: { callbacks: { label: (context) => `${context.dataset.label}: ${money.format(context.parsed.y)}` } } },
        scales: { x: { grid: { display: false } }, y: { beginAtZero: true, ticks: { callback: (value) => money.format(value) } } },
      },
    });
    const categories = summary.categories.filter((row) => row.amount > 0);
    if (categories.length) {
      new Chart(document.getElementById('category-chart'), {
        type: 'doughnut',
        data: { labels: categories.map((row) => row.name), datasets: [{
          data: categories.map((row) => row.amount / 100),
          backgroundColor: ['#277565', '#72a28b', '#b5cab6', '#d3bc8d', '#bb8876', '#77939a', '#8f86a5', '#bfd9d0'],
          borderWidth: 3, borderColor: '#fff',
        }] },
        options: { responsive: true, maintainAspectRatio: false, cutout: '72%', animation: reducedMotion ? false : undefined,
          plugins: { legend: { display: false }, tooltip: { callbacks: { label: (context) => `${context.label}: ${money.format(context.parsed)}` } } },
        },
      });
    } else {
      document.getElementById('category-chart').hidden = true;
      status.textContent = 'No hay gastos positivos en el mes seleccionado.';
    }
  } catch (_) {
    status.textContent = 'No se pudieron cargar las gráficas. Las tablas muestran los datos del periodo; recarga la página para reintentar.';
  }
}

drawCharts();
