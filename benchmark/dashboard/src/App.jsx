import { useEffect, useLayoutEffect, useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import './App.css'

const BACKEND_ORDER = ['filesystem', 'postgres', 'minio_s3', 'azure_blob', 'gcs', 'mongodb', 'redis']

const BACKEND_LABELS = {
  filesystem: 'Filesystem',
  postgres: 'PostgreSQL',
  minio_s3: 'S3 / MinIO',
  azure_blob: 'Azure Blob',
  gcs: 'Google Cloud Storage',
  mongodb: 'MongoDB',
  redis: 'Redis / Valkey',
}

const BACKEND_COLORS = {
  filesystem: '#34d399',
  postgres: '#94a3b8',
  minio_s3: '#fb923c',
  azure_blob: '#38bdf8',
  gcs: '#60a5fa',
  mongodb: '#10b981',
  redis: '#f87171',
}

const BACKEND_META = [
  {
    key: 'filesystem',
    icon: 'FS',
    title: 'Filesystem baseline',
    fit: 'Fast local control group used to anchor the benchmark story.',
    docs: 'https://github.com/langchain-ai/deepagents',
    caption: 'Bundled with Deep Agents and used here as the local baseline.',
  },
  {
    key: 'minio_s3',
    icon: 'S3',
    title: 'S3 / MinIO',
    fit: 'Object storage for binary payloads, shared assets, and cloud-native workflows.',
    docs: 'https://github.com/DiTo97/deepagents-backends/blob/main/wiki/s3.md',
    caption: 'Production-oriented S3 semantics with MinIO-backed local development.',
  },
  {
    key: 'postgres',
    icon: 'PG',
    title: 'PostgreSQL',
    fit: 'Relational durability, connection pooling, and consistent query behavior.',
    docs: 'https://github.com/DiTo97/deepagents-backends/blob/main/wiki/postgresql.md',
    caption: 'Best when the agent workspace should live in an operational database.',
  },
  {
    key: 'azure_blob',
    icon: 'AZ',
    title: 'Azure Blob',
    fit: 'Azure-native blob storage with Azurite parity for local integration testing.',
    docs: 'https://github.com/DiTo97/deepagents-backends/blob/main/wiki/azure-blob.md',
    caption: 'Fits teams standardizing on Microsoft cloud storage primitives.',
  },
  {
    key: 'gcs',
    icon: 'GC',
    title: 'Google Cloud Storage',
    fit: 'GCS-backed object storage with fake-gcs-server support in CI and development.',
    docs: 'https://github.com/DiTo97/deepagents-backends/blob/main/wiki/gcs.md',
    caption: 'A clean path for GCP deployments and portable benchmark runs.',
  },
  {
    key: 'mongodb',
    icon: 'MG',
    title: 'MongoDB',
    fit: 'Document persistence for metadata-heavy or schema-flexible agent workspaces.',
    docs: 'https://github.com/DiTo97/deepagents-backends/blob/main/wiki/mongodb.md',
    caption: 'Useful when file content and metadata should evolve together.',
  },
  {
    key: 'redis',
    icon: 'RD',
    title: 'Redis / Valkey',
    fit: 'Low-latency remote state for fast agent loops and ephemeral collaboration.',
    docs: 'https://github.com/DiTo97/deepagents-backends/blob/main/wiki/redis-valkey.md',
    caption: 'Optimized for speed-sensitive agent sessions and cache-like behavior.',
  },
]

const RESOURCE_LINKS = [
  {
    label: 'GitHub repository',
    href: 'https://github.com/DiTo97/deepagents-backends',
    detail: 'Source, releases, issues, and backend implementations.',
  },
  {
    label: 'Benchmark README',
    href: 'https://github.com/DiTo97/deepagents-backends/blob/main/benchmark/README.md',
    detail: 'Methodology, trace tables, and command-line entry point.',
  },
  {
    label: 'Pages workflow',
    href: 'https://github.com/DiTo97/deepagents-backends/blob/main/.github/workflows/pages.yml',
    detail: 'Static build and deploy pipeline for this dashboard.',
  },
  {
    label: 'Latest raw results',
    href: 'https://github.com/DiTo97/deepagents-backends/blob/main/benchmark/results/latest.json',
    detail: 'Machine-readable benchmark artifact consumed by this UI.',
  },
]

const candidateResultsUrls = (() => {
  const path = window.location.pathname.replace(/index\.html$/, '')
  const localRepoPath = path.endsWith('/benchmark/web/') || path.endsWith('/benchmark/web')
  return localRepoPath ? ['../results/latest.json', 'results/latest.json'] : ['results/latest.json', '../results/latest.json']
})()

function mean(values) {
  if (!values.length) {
    return 0
  }
  return values.reduce((total, value) => total + value, 0) / values.length
}

function formatMs(value) {
  return `${value.toFixed(1)} ms`
}

function formatPercent(value) {
  return `${Math.round(value * 100)}%`
}

function toSentenceCase(value) {
  return value.replaceAll('·', ' · ')
}

async function loadPayload() {
  for (const url of candidateResultsUrls) {
    try {
      const response = await fetch(url, { cache: 'no-store' })
      if (response.ok) {
        return await response.json()
      }
    } catch {
      // Try the next candidate path.
    }
  }

  throw new Error('Could not load benchmark/results/latest.json from any expected location.')
}

function StatCard({ label, value, detail }) {
  return (
    <article className="stat-card">
      <p>{label}</p>
      <strong>{value}</strong>
      <span>{detail}</span>
    </article>
  )
}

function SectionHeading({ eyebrow, title, description, extra }) {
  return (
    <div className="section-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
        {description ? <p className="section-copy">{description}</p> : null}
      </div>
      {extra}
    </div>
  )
}

function ChartTooltip({ active, payload, label, formatter, suffix }) {
  if (!active || !payload?.length) {
    return null
  }

  return (
    <div className="chart-tooltip">
      {label ? <p>{label}</p> : null}
      <ul>
        {payload.map((entry) => (
          <li key={entry.name ?? entry.dataKey}>
            <span>{entry.name ?? entry.dataKey}</span>
            <strong>
              {formatter ? formatter(entry.value) : entry.value}
              {suffix ?? ''}
            </strong>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ChartSurface({ children, ready = true }) {
  const [container, setContainer] = useState(null)
  const [size, setSize] = useState({ width: 0, height: 0 })

  useLayoutEffect(() => {
    if (!container) {
      return undefined
    }

    const updateSize = () => {
      setSize({
        width: container.clientWidth,
        height: container.clientHeight,
      })
    }

    updateSize()

    const observer = new ResizeObserver(updateSize)
    observer.observe(container)

    return () => observer.disconnect()
  }, [container])

  return (
    <div className="chart-frame" ref={setContainer}>
      {ready && size.width > 0 && size.height > 0 ? (
        children(size)
      ) : (
        <div className="chart-empty">Loading chart…</div>
      )}
    </div>
  )
}

function App() {
  const [payload, setPayload] = useState(null)
  const [error, setError] = useState('')
  const [operation, setOperation] = useState('')
  const [traceId, setTraceId] = useState('')
  const [query, setQuery] = useState('')
  const [shape, setShape] = useState('all')

  useEffect(() => {
    let cancelled = false

    loadPayload()
      .then((data) => {
        if (!cancelled) {
          setPayload(data)
        }
      })
      .catch((loadError) => {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : 'Unknown benchmark loading error.')
        }
      })

    return () => {
      cancelled = true
    }
  }, [])

  const traces = useMemo(() => payload?.traces ?? [], [payload])

  const summary = useMemo(() => {
    if (!payload) {
      return []
    }

    const averageLatency = BACKEND_ORDER.map((backend) => {
      const values = traces
        .map((trace) => trace.backends[backend]?.median_total_ms)
        .filter((value) => typeof value === 'number')
      return {
        backend,
        label: BACKEND_LABELS[backend],
        latency: mean(values),
        correctness: mean(
          traces
            .map((trace) => trace.backends[backend]?.correctness_rate)
            .filter((value) => typeof value === 'number'),
        ),
      }
    })

    const fastest = averageLatency.reduce((best, current) =>
      current.latency > 0 && current.latency < best.latency ? current : best,
    )

    return [
      {
        label: 'Benchmark suite',
        value: `${traces.length}`,
        detail: 'realistic replay traces',
      },
      {
        label: 'Supported backends',
        value: `${BACKEND_META.length}`,
        detail: 'remote targets plus filesystem baseline',
      },
      {
        label: 'Fastest average',
        value: fastest.label,
        detail: `${formatMs(fastest.latency)} median latency across the suite`,
      },
      {
        label: 'Correctness envelope',
        value: formatPercent(Math.max(...averageLatency.map((entry) => entry.correctness))),
        detail: `${payload.measured_runs} measured runs after ${payload.warmup_runs} warmup pass`,
      },
    ]
  }, [payload, traces])

  const averageLatencyData = useMemo(
    () =>
      BACKEND_ORDER.map((backend) => ({
        key: backend,
        backend: BACKEND_LABELS[backend],
        latency: mean(
          traces
            .map((trace) => trace.backends[backend]?.median_total_ms)
            .filter((value) => typeof value === 'number'),
        ),
        fill: BACKEND_COLORS[backend],
      })),
    [traces],
  )

  const correctnessScatterData = useMemo(
    () =>
      BACKEND_ORDER.map((backend) => ({
        key: backend,
        backend: BACKEND_LABELS[backend],
        latency: mean(
          traces
            .map((trace) => trace.backends[backend]?.median_total_ms)
            .filter((value) => typeof value === 'number'),
        ),
        correctness:
          mean(
            traces
              .map((trace) => trace.backends[backend]?.correctness_rate)
              .filter((value) => typeof value === 'number'),
          ) * 100,
        fill: BACKEND_COLORS[backend],
      })),
    [traces],
  )

  const operations = useMemo(() => {
    const allOperations = new Set()
    traces.forEach((trace) => {
      Object.values(trace.backends).forEach((backend) => {
        Object.keys(backend.per_op_stats ?? {}).forEach((opName) => allOperations.add(opName))
      })
    })
    return Array.from(allOperations).sort()
  }, [traces])

  const selectedOperation = operations.includes(operation) ? operation : operations[0] ?? ''
  const selectedTraceId = traces.some((trace) => trace.trace_id === traceId) ? traceId : traces[0]?.trace_id ?? ''

  const perOperationData = useMemo(
    () =>
      BACKEND_ORDER.map((backend) => ({
        key: backend,
        backend: BACKEND_LABELS[backend],
        latency: mean(
          traces
            .map((trace) => trace.backends[backend]?.per_op_stats?.[selectedOperation]?.p50)
            .filter((value) => typeof value === 'number'),
        ),
        fill: BACKEND_COLORS[backend],
      })),
    [selectedOperation, traces],
  )

  const selectedTrace = useMemo(
    () => traces.find((trace) => trace.trace_id === selectedTraceId) ?? traces[0] ?? null,
    [selectedTraceId, traces],
  )

  const traceComparisonData = useMemo(() => {
    if (!selectedTrace) {
      return []
    }

    return BACKEND_ORDER.map((backend) => ({
      key: backend,
      backend: BACKEND_LABELS[backend],
      latency: selectedTrace.backends[backend]?.median_total_ms ?? 0,
      fill: BACKEND_COLORS[backend],
    }))
  }, [selectedTrace])

  const shapes = useMemo(
    () => ['all', ...new Set(traces.map((trace) => trace.tags.shape).filter(Boolean))],
    [traces],
  )

  const filteredTraces = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    return traces.filter((trace) => {
      const matchesQuery =
        !normalizedQuery ||
        `${trace.trace_id} ${trace.fixture_id} ${trace.tags.shape}`.toLowerCase().includes(normalizedQuery)
      const matchesShape = shape === 'all' || trace.tags.shape === shape
      return matchesQuery && matchesShape
    })
  }, [query, shape, traces])

  const benchmarkMeta = payload
    ? `Generated ${new Date(payload.generated_at).toLocaleString()} • Python ${payload.environment.python_version} • ${payload.environment.platform}`
    : 'Loading benchmark snapshot…'
  const chartsReady = Boolean(payload && selectedOperation && selectedTrace && averageLatencyData.length)

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top">
          <span className="brand-mark">DB</span>
          <span>
            <strong>Deep Agents Backends</strong>
            <small>benchmark dashboard</small>
          </span>
        </a>
        <nav>
          <a href="#overview">Overview</a>
          <a href="#backends">Backends</a>
          <a href="#benchmark">Benchmark</a>
          <a href="#resources">Resources</a>
        </nav>
      </header>

      <main id="top">
        <section id="overview" className="hero-panel">
          <div className="hero-copy">
            <p className="eyebrow">Remote persistence for Deep Agents</p>
            <h1>Production-ready backend adapters, benchmarked and packaged for real agent deployments.</h1>
            <p className="lead">
              <a href="https://github.com/DiTo97/deepagents-backends">deepagents-backends</a> extends{' '}
              <a href="https://github.com/langchain-ai/deepagents">LangChain Deep Agents</a> with curated S3,
              PostgreSQL, Azure Blob, Google Cloud Storage, MongoDB, and Redis / Valkey integrations.
            </p>
            <div className="hero-actions">
              <a className="button button-primary" href="https://pypi.org/project/deepagents-backends/">
                View on PyPI
              </a>
              <a className="button button-secondary" href="https://github.com/DiTo97/deepagents-backends">
                Browse repository
              </a>
              <a className="button button-secondary" href="https://github.com/DiTo97/deepagents-backends/tree/main/wiki">
                Read backend guides
              </a>
            </div>
            <div className="install-card">
              <span>Quick start</span>
              <code>pip install deepagents-backends</code>
            </div>
          </div>

          <aside className="hero-aside">
            <div className="hero-highlight">
              <span className="eyebrow">What you ship</span>
              <ul>
                <li>BackendProtocol-compatible remote storage adapters</li>
                <li>Docker-based integration matrix for every supported service</li>
                <li>Trace-driven benchmark harness and publishable static dashboard</li>
              </ul>
            </div>
            <div className="hero-highlight subdued">
              <span className="eyebrow">Key repository entry points</span>
              <dl>
                <div>
                  <dt>Package</dt>
                  <dd>/src/deepagents_backends</dd>
                </div>
                <div>
                  <dt>Benchmark harness</dt>
                  <dd>/benchmark/run.py</dd>
                </div>
                <div>
                  <dt>Docs</dt>
                  <dd>/wiki/* and /benchmark/README.md</dd>
                </div>
              </dl>
            </div>
          </aside>
        </section>

        <section className="stats-grid">
          {summary.map((entry) => (
            <StatCard key={entry.label} {...entry} />
          ))}
        </section>

        <section id="backends" className="section-block">
          <SectionHeading
            eyebrow="Supported backends"
            title="Choose the persistence model that matches the agent workload"
            description="Every backend is documented, benchmarked against the same realistic traces, and designed to drop into the Deep Agents storage interface."
          />
          <div className="backend-grid">
            {BACKEND_META.map((backend) => (
              <article key={backend.key} className="backend-card">
                <div className="backend-card-top">
                  <span className="backend-icon" style={{ borderColor: `${BACKEND_COLORS[backend.key]}66` }}>
                    {backend.icon}
                  </span>
                  <span className="backend-chip">{backend.fit}</span>
                </div>
                <h3>{backend.title}</h3>
                <p>{backend.caption}</p>
                <a href={backend.docs}>Open guide →</a>
              </article>
            ))}
          </div>
        </section>

        <section className="section-block split-grid">
          <article className="panel feature-panel">
            <SectionHeading
              eyebrow="Architecture"
              title="How the package plugs into Deep Agents"
              description="The adapters implement the upstream backend protocol and are exercised by the same benchmark harness used to build this dashboard."
            />
            <img src="./assets/architecture.svg" alt="Architecture diagram for Deep Agents Backends" />
          </article>

          <article id="resources" className="panel resource-panel">
            <SectionHeading
              eyebrow="Curated links"
              title="Repository paths worth knowing"
              description="These are the canonical entry points for source, docs, the raw benchmark artifact, and the static deployment pipeline."
            />
            <div className="resource-list">
              {RESOURCE_LINKS.map((resource) => (
                <a key={resource.href} className="resource-card" href={resource.href}>
                  <strong>{resource.label}</strong>
                  <span>{resource.detail}</span>
                </a>
              ))}
            </div>
          </article>
        </section>

        <section id="benchmark" className="section-block benchmark-section">
          <SectionHeading
            eyebrow="Benchmark explorer"
            title="Visualize the latest committed benchmark run"
            description="The charts below read the current benchmark JSON snapshot and render a static, dependency-bundled dashboard with no CDN runtime requirements."
            extra={<p className="benchmark-meta">{benchmarkMeta}</p>}
          />

          {error ? <div className="error-banner">{error}</div> : null}

          <div className="chart-grid chart-grid-primary">
            <article className="panel chart-panel">
              <div className="panel-header">
                <div>
                  <h3>Average median trace latency</h3>
                  <p>Lower is better across the full realistic replay suite.</p>
                </div>
              </div>
              <ChartSurface ready={chartsReady}>
                {({ width, height }) => (
                  <BarChart width={width} height={height} data={averageLatencyData} margin={{ top: 12, right: 12, left: -16, bottom: 12 }}>
                    <CartesianGrid stroke="rgba(148, 163, 184, 0.16)" vertical={false} />
                    <XAxis dataKey="backend" tickLine={false} axisLine={false} tick={{ fill: '#cbd5e1', fontSize: 12 }} />
                    <YAxis
                      tickLine={false}
                      axisLine={false}
                      tick={{ fill: '#cbd5e1', fontSize: 12 }}
                      tickFormatter={(value) => `${value} ms`}
                    />
                    <Tooltip content={<ChartTooltip formatter={formatMs} />} />
                    <Bar dataKey="latency" radius={[14, 14, 6, 6]}>
                      {averageLatencyData.map((entry) => (
                        <Cell key={entry.key} fill={entry.fill} />
                      ))}
                    </Bar>
                  </BarChart>
                )}
              </ChartSurface>
            </article>

            <article className="panel chart-panel">
              <div className="panel-header">
                <div>
                  <h3>Correctness versus latency</h3>
                  <p>Find the balance between remote-storage speed and correctness retention.</p>
                </div>
              </div>
              <ChartSurface ready={chartsReady}>
                {({ width, height }) => (
                  <ScatterChart width={width} height={height} margin={{ top: 12, right: 24, left: 0, bottom: 12 }}>
                    <CartesianGrid stroke="rgba(148, 163, 184, 0.16)" />
                    <XAxis
                      type="number"
                      dataKey="latency"
                      name="Latency"
                      tick={{ fill: '#cbd5e1', fontSize: 12 }}
                      tickFormatter={(value) => `${value} ms`}
                    />
                    <YAxis
                      type="number"
                      dataKey="correctness"
                      name="Correctness"
                      domain={[0, 100]}
                      tick={{ fill: '#cbd5e1', fontSize: 12 }}
                      tickFormatter={(value) => `${value}%`}
                    />
                    <Tooltip
                      cursor={{ strokeDasharray: '4 4' }}
                      content={<ChartTooltip formatter={(value) => value} />}
                    />
                    <Scatter data={correctnessScatterData}>
                      {correctnessScatterData.map((entry) => (
                        <Cell key={entry.key} fill={entry.fill} />
                      ))}
                    </Scatter>
                  </ScatterChart>
                )}
              </ChartSurface>
              <div className="chart-legend">
                {correctnessScatterData.map((entry) => (
                  <span key={entry.key}>
                    <i style={{ background: entry.fill }}></i>
                    {entry.backend}
                  </span>
                ))}
              </div>
            </article>
          </div>

          <div className="chart-grid chart-grid-secondary">
            <article className="panel chart-panel">
              <div className="panel-header panel-header-stack">
                <div>
                  <h3>Per-operation latency</h3>
                  <p>P50 latency averaged across traces for a selected backend operation.</p>
                </div>
                <label className="control">
                  <span>Operation</span>
                  <select value={selectedOperation} onChange={(event) => setOperation(event.target.value)}>
                    {operations.map((opName) => (
                      <option key={opName} value={opName}>
                        {opName}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <ChartSurface ready={chartsReady}>
                {({ width, height }) => (
                  <BarChart width={width} height={height} data={perOperationData} margin={{ top: 12, right: 12, left: -16, bottom: 12 }}>
                    <CartesianGrid stroke="rgba(148, 163, 184, 0.16)" vertical={false} />
                    <XAxis dataKey="backend" tickLine={false} axisLine={false} tick={{ fill: '#cbd5e1', fontSize: 12 }} />
                    <YAxis
                      tickLine={false}
                      axisLine={false}
                      tick={{ fill: '#cbd5e1', fontSize: 12 }}
                      tickFormatter={(value) => `${value} ms`}
                    />
                    <Tooltip content={<ChartTooltip formatter={formatMs} />} />
                    <Bar dataKey="latency" radius={[14, 14, 6, 6]}>
                      {perOperationData.map((entry) => (
                        <Cell key={entry.key} fill={entry.fill} />
                      ))}
                    </Bar>
                  </BarChart>
                )}
              </ChartSurface>
            </article>

            <article className="panel chart-panel">
              <div className="panel-header panel-header-stack">
                <div>
                  <h3>Trace drill-down</h3>
                  <p>Inspect the backend median latency for a single realistic trace.</p>
                </div>
                <label className="control">
                  <span>Trace</span>
                  <select value={selectedTraceId} onChange={(event) => setTraceId(event.target.value)}>
                    {traces.map((trace) => (
                      <option key={trace.trace_id} value={trace.trace_id}>
                        {trace.trace_id}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <ChartSurface ready={chartsReady}>
                {({ width, height }) => (
                  <BarChart width={width} height={height} data={traceComparisonData} margin={{ top: 12, right: 12, left: -16, bottom: 12 }}>
                    <CartesianGrid stroke="rgba(148, 163, 184, 0.16)" vertical={false} />
                    <XAxis dataKey="backend" tickLine={false} axisLine={false} tick={{ fill: '#cbd5e1', fontSize: 12 }} />
                    <YAxis
                      tickLine={false}
                      axisLine={false}
                      tick={{ fill: '#cbd5e1', fontSize: 12 }}
                      tickFormatter={(value) => `${value} ms`}
                    />
                    <Tooltip content={<ChartTooltip formatter={formatMs} />} />
                    <Bar dataKey="latency" radius={[14, 14, 6, 6]}>
                      {traceComparisonData.map((entry) => (
                        <Cell key={entry.key} fill={entry.fill} />
                      ))}
                    </Bar>
                  </BarChart>
                )}
              </ChartSurface>
            </article>
          </div>

          <article className="panel table-panel">
            <div className="panel-header panel-header-stack">
              <div>
                <h3>Trace summary table</h3>
                <p>Search or filter the suite to compare specific traces, fixtures, and fastest backends.</p>
              </div>
              <div className="control-row">
                <label className="control grow">
                  <span>Search</span>
                  <input
                    type="search"
                    placeholder="Search trace or fixture"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                  />
                </label>
                <label className="control">
                  <span>Shape</span>
                  <select value={shape} onChange={(event) => setShape(event.target.value)}>
                    {shapes.map((shapeValue) => (
                      <option key={shapeValue} value={shapeValue}>
                        {shapeValue === 'all' ? 'All shapes' : toSentenceCase(shapeValue)}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>

            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Trace</th>
                    <th>Shape</th>
                    <th>Fixture</th>
                    <th>Fastest backend</th>
                    <th>Steps</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredTraces.map((trace) => {
                    const fastest = BACKEND_ORDER.reduce((best, backend) => {
                      const latency = trace.backends[backend]?.median_total_ms
                      if (typeof latency !== 'number') {
                        return best
                      }
                      if (!best || latency < best.latency) {
                        return { backend, latency }
                      }
                      return best
                    }, null)

                    return (
                      <tr key={trace.trace_id}>
                        <td>{trace.trace_id}</td>
                        <td>{toSentenceCase(trace.tags.shape)}</td>
                        <td>{trace.fixture_id}</td>
                        <td>{fastest ? BACKEND_LABELS[fastest.backend] : '—'}</td>
                        <td>{trace.step_count}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </article>
        </section>
      </main>
    </div>
  )
}

export default App
