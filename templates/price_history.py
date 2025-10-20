{% extends "base.html" %}
{% block content %}

<div class="container py-5">
  <h1 class="h3 mb-4">📊 Preis-Statistiken</h1>

  <!-- Suche nach Preis-Historie -->
  <div class="card mb-4">
    <div class="card-body">
      <form method="get" action="{{ url_for('stats.price_trend') }}">
        <div class="row g-3">
          <div class="col-md-8">
            <label class="form-label">Suchbegriff</label>
            <input type="text" name="q" class="form-control" placeholder="z.B. iPhone 15 Pro" value="{{ request.args.get('q', '') }}" required>
          </div>
          <div class="col-md-2">
            <label class="form-label">Zeitraum</label>
            <select name="days" class="form-select">
              <option value="7">7 Tage</option>
              <option value="14">14 Tage</option>
              <option value="30" selected>30 Tage</option>
              <option value="90">90 Tage</option>
            </select>
          </div>
          <div class="col-md-2 d-flex align-items-end">
            <button type="submit" class="btn btn-primary w-100">Analysieren</button>
          </div>
        </div>
      </form>
    </div>
  </div>

  {% if trend %}
    {% if trend.found %}
      <!-- Preis-Trend Ergebnis -->
      <div class="row g-4 mb-4">
        <div class="col-md-3">
          <div class="card">
            <div class="card-body text-center">
              <h6 class="text-muted">Aktueller Ø-Preis</h6>
              <h2 class="mb-0">{{ trend.current_avg }}€</h2>
            </div>
          </div>
        </div>

        <div class="col-md-3">
          <div class="card">
            <div class="card-body text-center">
              <h6 class="text-muted">Trend ({{ trend.days }} Tage)</h6>
              <h2 class="mb-0">
                {% if trend.trend == 'rising' %}
                  <span class="text-danger">↗ {{ trend.change_percent }}%</span>
                {% elif trend.trend == 'falling' %}
                  <span class="text-success">↘ {{ trend.change_percent }}%</span>
                {% else %}
                  <span class="text-secondary">→ {{ trend.change_percent }}%</span>
                {% endif %}
              </h2>
            </div>
          </div>
        </div>

        <div class="col-md-3">
          <div class="card">
            <div class="card-body text-center">
              <h6 class="text-muted">Vor {{ trend.days }} Tagen</h6>
              <h2 class="mb-0">{{ trend.oldest_avg }}€</h2>
            </div>
          </div>
        </div>

        <div class="col-md-3">
          <div class="card">
            <div class="card-body text-center">
              <h6 class="text-muted">Datenpunkte</h6>
              <h2 class="mb-0">{{ trend.history|length }}</h2>
            </div>
          </div>
        </div>
      </div>

      <!-- Chart -->
      <div class="card">
        <div class="card-header">
          <h5 class="mb-0">Preisverlauf: {{ trend.search_term }}</h5>
        </div>
        <div class="card-body">
          <canvas id="priceChart" height="100"></canvas>
        </div>
      </div>

      <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
      <script>
        const ctx = document.getElementById('priceChart');

        const labels = {{ trend.history | map(attribute='date') | list | tojson }};
        const avgPrices = {{ trend.history | map(attribute='avg_price') | list | tojson }};
        const minPrices = {{ trend.history | map(attribute='min_price') | list | tojson }};
        const maxPrices = {{ trend.history | map(attribute='max_price') | list | tojson }};

        new Chart(ctx, {
          type: 'line',
          data: {
            labels: labels,
            datasets: [
              {
                label: 'Durchschnittspreis',
                data: avgPrices,
                borderColor: 'rgb(13, 110, 253)',
                backgroundColor: 'rgba(13, 110, 253, 0.1)',
                tension: 0.3,
                fill: true
              },
              {
                label: 'Min-Preis',
                data: minPrices,
                borderColor: 'rgb(40, 167, 69)',
                borderDash: [5, 5],
                tension: 0.3,
                fill: false
              },
              {
                label: 'Max-Preis',
                data: maxPrices,
                borderColor: 'rgb(220, 53, 69)',
                borderDash: [5, 5],
                tension: 0.3,
                fill: false
              }
            ]
          },
          options: {
            responsive: true,
            plugins: {
              legend: {
                display: true,
                position: 'top'
              },
              tooltip: {
                mode: 'index',
                intersect: false
              }
            },
            scales: {
              y: {
                beginAtZero: false,
                ticks: {
                  callback: function(value) {
                    return value + '€';
                  }
                }
              }
            }
          }
        });
      </script>

    {% else %}
      <div class="alert alert-warning">
        <h5>Keine Daten verfügbar</h5>
        <p>Für "{{ request.args.get('q') }}" sind noch keine Preis-Daten vorhanden.</p>
        <p class="mb-0">Erstelle einen Alert für diesen Suchbegriff und wir beginnen mit der Preis-Erfassung.</p>
      </div>
    {% endif %}
  {% else %}
    <!-- Beliebte Suchen -->
    <div class="card">
      <div class="card-header">
        <h5 class="mb-0">🔥 Beliebte Suchbegriffe</h5>
      </div>
      <div class="card-body">
        <div class="table-responsive">
          <table class="table">
            <thead>
              <tr>
                <th>Suchbegriff</th>
                <th>Ø-Preis</th>
                <th>Analysen</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {% for item in popular_searches %}
                <tr>
                  <td>{{ item.search_term }}</td>
                  <td><strong>{{ item.avg_price }}€</strong></td>
                  <td>{{ item.searches }}</td>
                  <td>
                    <a href="?q={{ item.search_term }}&days=30" class="btn btn-sm btn-outline-primary">
                      Ansehen
                    </a>
                  </td>
                </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  {% endif %}
</div>

{% endblock %}
