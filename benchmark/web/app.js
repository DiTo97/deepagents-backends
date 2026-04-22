const BACKEND_ORDER = ["filesystem", "postgres", "minio_s3", "azure_blob", "gcs", "mongodb", "redis"];
const BACKEND_LABELS = {
  filesystem: "Filesystem",
  postgres: "PostgreSQL",
  minio_s3: "S3 / MinIO",
  azure_blob: "Azure Blob",
  gcs: "GCS",
  mongodb: "MongoDB",
  redis: "Redis / Valkey",
};
const BACKEND_COLORS = {
  filesystem: "#22c55e",
  postgres: "#94a3b8",
  minio_s3: "#fb923c",
  azure_blob: "#38bdf8",
  gcs: "#60a5fa",
  mongodb: "#34d399",
  redis: "#ef4444",
};
const BACKEND_META = [
  {
    key: "minio_s3",
    title: "S3 / MinIO",
    icon: "https://cdn.simpleicons.org/minio/ffffff",
    fit: "Object storage, shared assets, binary payloads",
    docs: "https://github.com/DiTo97/deepagents-backends/blob/main/wiki/s3.md",
  },
  {
    key: "postgres",
    title: "PostgreSQL",
    icon: "https://cdn.simpleicons.org/postgresql/ffffff",
    fit: "Relational persistence, pooling, strong query semantics",
    docs: "https://github.com/DiTo97/deepagents-backends/blob/main/wiki/postgresql.md",
  },
  {
    key: "azure_blob",
    title: "Azure Blob",
    icon: "https://cdn.simpleicons.org/microsoftazure/ffffff",
    fit: "Azure-native blob storage and Azurite-local development",
    docs: "https://github.com/DiTo97/deepagents-backends/blob/main/wiki/azure-blob.md",
  },
  {
    key: "gcs",
    title: "Google Cloud Storage",
    icon: "https://cdn.simpleicons.org/googlecloud/ffffff",
    fit: "GCS-compatible object storage with fake-gcs-server testing",
    docs: "https://github.com/DiTo97/deepagents-backends/blob/main/wiki/gcs.md",
  },
  {
    key: "mongodb",
    title: "MongoDB",
    icon: "https://cdn.simpleicons.org/mongodb/ffffff",
    fit: "Document persistence for flexible file metadata and content",
    docs: "https://github.com/DiTo97/deepagents-backends/blob/main/wiki/mongodb.md",
  },
  {
    key: "redis",
    title: "Redis / Valkey",
    icon: "https://cdn.simpleicons.org/redis/ffffff",
    fit: "Low-latency key-value persistence for fast agent workspaces",
    docs: "https://github.com/DiTo97/deepagents-backends/blob/main/wiki/redis-valkey.md",
  },
];

const candidateResultsUrls = ["results/latest.json", "../results/latest.json", "./benchmark/results/latest.json"];
const chartRegistry = {};

function mean(values) {
  return values.length ? values.reduce((total, value) => total + value, 0) / values.length : 0;
}

function formatMs(value) {
  return `${value.toFixed(1)} ms`;
}

function formatPercent(value) {
  return `${(value * 100).toFixed(0)}%`;
}

function backendValues(traces, selector) {
  return BACKEND_ORDER.map((backend) => {
    const values = traces
      .map((trace) => selector(trace.backends[backend]))
      .filter((value) => typeof value === "number" && Number.isFinite(value));
    return mean(values);
  });
}

function findFastestBackend(trace) {
  let fastest = null;
  let fastestValue = Number.POSITIVE_INFINITY;

  for (const backend of BACKEND_ORDER) {
    const value = trace.backends[backend]?.median_total_ms;
    if (typeof value === "number" && value < fastestValue) {
      fastest = backend;
      fastestValue = value;
    }
  }

  return fastest;
}

function renderBackendCards() {
  const container = document.getElementById("backend-grid");
  container.innerHTML = "";

  for (const backend of BACKEND_META) {
    const card = document.createElement("article");
    card.className = "backend-card";
    card.innerHTML = `
      <div class="flex items-start justify-between gap-4">
        <img class="backend-icon" src="${backend.icon}" alt="${backend.title} logo" loading="lazy" />
        <span class="backend-tag">${backend.fit}</span>
      </div>
      <div>
        <h3 class="text-xl font-semibold text-white">${backend.title}</h3>
        <p class="mt-2 text-sm leading-6 text-slate-300">${backend.fit}</p>
      </div>
      <a class="text-sm font-medium text-sky-300 hover:text-sky-200" href="${backend.docs}">Open backend guide →</a>
    `;
    container.appendChild(card);
  }
}

function renderSummaryCards(payload) {
  const traces = payload.traces;
  const averageLatency = backendValues(traces, (backend) => backend?.median_total_ms);
  const positiveLatencies = averageLatency.filter((value) => value > 0);
  const bestLatency = positiveLatencies.length ? Math.min(...positiveLatencies) : null;
  const fastestBackend = bestLatency !== null ? BACKEND_LABELS[BACKEND_ORDER[averageLatency.indexOf(bestLatency)]] : "N/A";
  const cards = [
    {
      label: "Benchmark suite",
      value: `${traces.length}`,
      subtext: "realistic replay traces",
    },
    {
      label: "Supported backends",
      value: `${BACKEND_META.length}`,
      subtext: "remote backends plus filesystem baseline",
    },
    {
      label: "Fastest average",
      value: fastestBackend,
      subtext: bestLatency !== null ? `${formatMs(bestLatency)} average median latency` : "no data available",
    },
    {
      label: "Run profile",
      value: `${payload.measured_runs}×`,
      subtext: `${payload.warmup_runs} warmup run per trace`,
    },
  ];

  document.getElementById("summary-cards").innerHTML = cards
    .map(
      (card) => `
        <div class="metric-card">
          <div class="metric-label">${card.label}</div>
          <div class="metric-value">${card.value}</div>
          <div class="metric-subtext">${card.subtext}</div>
        </div>
      `,
    )
    .join("");

  document.getElementById("benchmark-meta").textContent = `Generated ${new Date(payload.generated_at).toLocaleString()} • Python ${payload.environment.python_version} • ${payload.environment.platform}`;
}

function buildBarChart(canvasId, labels, values, label, colors) {
  const context = document.getElementById(canvasId);
  if (chartRegistry[canvasId]) {
    chartRegistry[canvasId].destroy();
  }

  chartRegistry[canvasId] = new Chart(context, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label,
          data: values,
          borderRadius: 12,
          backgroundColor: colors,
          borderColor: colors,
          borderWidth: 1,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label(context) {
              return `${context.dataset.label}: ${formatMs(context.raw)}`;
            },
          },
        },
      },
      scales: {
        x: {
          ticks: { color: "#cbd5e1" },
          grid: { display: false },
        },
        y: {
          ticks: {
            color: "#cbd5e1",
            callback(value) {
              return `${value} ms`;
            },
          },
          grid: { color: "rgba(148, 163, 184, 0.16)" },
        },
      },
    },
  });
}

function buildScatterChart(payload) {
  const context = document.getElementById("correctness-chart");
  if (chartRegistry.correctness) {
    chartRegistry.correctness.destroy();
  }

  const data = BACKEND_ORDER.map((backend) => {
    const traces = payload.traces;
    const latency = mean(
      traces
        .map((trace) => trace.backends[backend]?.median_total_ms)
        .filter((value) => typeof value === "number"),
    );
    const correctness = mean(
      traces
        .map((trace) => trace.backends[backend]?.correctness_rate)
        .filter((value) => typeof value === "number"),
    );

    return {
      label: BACKEND_LABELS[backend],
      data: [{ x: latency, y: correctness * 100 }],
      pointRadius: 7,
      pointHoverRadius: 9,
      borderColor: BACKEND_COLORS[backend],
      backgroundColor: BACKEND_COLORS[backend],
    };
  });

  chartRegistry.correctness = new Chart(context, {
    type: "scatter",
    data: { datasets: data },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: {
          labels: { color: "#e2e8f0" },
        },
        tooltip: {
          callbacks: {
            label(context) {
              return `${context.dataset.label}: ${formatMs(context.raw.x)}, ${context.raw.y.toFixed(0)}% correct`;
            },
          },
        },
      },
      scales: {
        x: {
          title: { display: true, text: "Average median latency", color: "#cbd5e1" },
          ticks: {
            color: "#cbd5e1",
            callback(value) {
              return `${value} ms`;
            },
          },
          grid: { color: "rgba(148, 163, 184, 0.16)" },
        },
        y: {
          min: 0,
          max: 100,
          title: { display: true, text: "Correctness rate", color: "#cbd5e1" },
          ticks: {
            color: "#cbd5e1",
            callback(value) {
              return `${value}%`;
            },
          },
          grid: { color: "rgba(148, 163, 184, 0.16)" },
        },
      },
    },
  });
}

function renderOperationChart(payload) {
  const opSelect = document.getElementById("op-select");
  const operations = Array.from(
    new Set(payload.traces.flatMap((trace) => Object.values(trace.backends).flatMap((backend) => Object.keys(backend.per_op_stats || {})))),
  ).sort();

  opSelect.replaceChildren(
    ...operations.map((op) => {
      const option = document.createElement("option");
      option.value = op;
      option.textContent = op;
      return option;
    }),
  );

  const update = () => {
    const op = opSelect.value;
    const values = BACKEND_ORDER.map((backend) => {
      const matches = payload.traces
        .map((trace) => trace.backends[backend]?.per_op_stats?.[op]?.p50)
        .filter((value) => typeof value === "number");
      return mean(matches);
    });

    buildBarChart(
      "operation-chart",
      BACKEND_ORDER.map((backend) => BACKEND_LABELS[backend]),
      values,
      `${op} p50 latency`,
      BACKEND_ORDER.map((backend) => BACKEND_COLORS[backend]),
    );
  };

  opSelect.addEventListener("change", update);
  update();
}

function renderTraceChart(payload) {
  const traceSelect = document.getElementById("trace-select");
  traceSelect.replaceChildren(
    ...payload.traces.map((trace) => {
      const option = document.createElement("option");
      option.value = trace.trace_id;
      option.textContent = trace.trace_id;
      return option;
    }),
  );

  const update = () => {
    const selectedTrace = payload.traces.find((trace) => trace.trace_id === traceSelect.value) || payload.traces[0];
    const values = BACKEND_ORDER.map((backend) => selectedTrace.backends[backend]?.median_total_ms ?? 0);
    buildBarChart(
      "trace-chart",
      BACKEND_ORDER.map((backend) => BACKEND_LABELS[backend]),
      values,
      `${selectedTrace.trace_id} median latency`,
      BACKEND_ORDER.map((backend) => BACKEND_COLORS[backend]),
    );
  };

  traceSelect.addEventListener("change", update);
  update();
}

function renderTraceTable(payload) {
  const searchInput = document.getElementById("trace-search");
  const shapeFilter = document.getElementById("shape-filter");
  const tableBody = document.getElementById("trace-table-body");
  const shapes = Array.from(new Set(payload.traces.map((trace) => trace.tags.shape))).sort();
  for (const shape of shapes) {
    const option = document.createElement("option");
    option.value = shape;
    option.textContent = shape;
    shapeFilter.appendChild(option);
  }

  const draw = () => {
    const query = searchInput.value.trim().toLowerCase();
    const shapeValue = shapeFilter.value;
    const rows = payload.traces.filter((trace) => {
      const matchesQuery = !query || `${trace.trace_id} ${trace.fixture_id}`.toLowerCase().includes(query);
      const matchesShape = shapeValue === "all" || trace.tags.shape === shapeValue;
      return matchesQuery && matchesShape;
    });

    tableBody.replaceChildren(
      ...rows.map((trace) => {
        const fastest = findFastestBackend(trace);
        const tr = document.createElement("tr");

        const tdId = document.createElement("td");
        tdId.className = "px-6 py-4 font-medium text-white";
        tdId.textContent = trace.trace_id;

        const tdShape = document.createElement("td");
        tdShape.className = "px-6 py-4 text-slate-300";
        tdShape.textContent = trace.tags.shape;

        const tdFixture = document.createElement("td");
        tdFixture.className = "px-6 py-4 text-slate-300";
        tdFixture.textContent = trace.fixture_id;

        const tdFastest = document.createElement("td");
        tdFastest.className = "px-6 py-4 text-sky-300";
        tdFastest.textContent = BACKEND_LABELS[fastest] ?? "-";

        const tdSteps = document.createElement("td");
        tdSteps.className = "px-6 py-4 text-slate-300";
        tdSteps.textContent = trace.step_count;

        tr.append(tdId, tdShape, tdFixture, tdFastest, tdSteps);
        return tr;
      }),
    );
  };

  searchInput.addEventListener("input", draw);
  shapeFilter.addEventListener("change", draw);
  draw();
}

async function loadPayload() {
  for (const url of candidateResultsUrls) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (response.ok) {
        return await response.json();
      }
    } catch (_error) {
      // Try the next candidate path.
    }
  }

  throw new Error("Could not load benchmark/results/latest.json from any expected location.");
}

function showError(message) {
  const banner = document.getElementById("error-banner");
  banner.textContent = message;
  banner.classList.remove("hidden");
}

async function main() {
  renderBackendCards();

  try {
    const payload = await loadPayload();
    renderSummaryCards(payload);

    const averageLatency = backendValues(payload.traces, (backend) => backend?.median_total_ms);
    buildBarChart(
      "backend-latency-chart",
      BACKEND_ORDER.map((backend) => BACKEND_LABELS[backend]),
      averageLatency,
      "Average median latency",
      BACKEND_ORDER.map((backend) => BACKEND_COLORS[backend]),
    );
    buildScatterChart(payload);
    renderOperationChart(payload);
    renderTraceChart(payload);
    renderTraceTable(payload);
  } catch (error) {
    console.error(error);
    showError(error instanceof Error ? error.message : "Unknown benchmark loading error.");
  }
}

main();
