import { useHealth } from '../api/health'

export function DashboardPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Dashboard</h1>
      <SystemStatus />
    </div>
  )
}

/** Shows that the frontend, API and database are connected. Replaced by real KPIs in Phase 6. */
function SystemStatus() {
  const { data, isPending, isError, error } = useHealth()

  let apiStatus = 'Checking...'
  let databaseStatus = 'Checking...'
  if (isError) {
    apiStatus = `Unavailable (${error.message})`
    databaseStatus = 'Unknown'
  } else if (!isPending) {
    apiStatus = 'Connected'
    databaseStatus = data.database === 'ok' ? 'Connected' : 'Unavailable'
  }

  return (
    <section aria-labelledby="system-status" className="max-w-md rounded-lg border border-slate-200 bg-white p-6">
      <h2 id="system-status" className="mb-4 text-lg font-semibold">
        System status
      </h2>
      <dl className="grid grid-cols-2 gap-y-2 text-sm">
        <dt className="text-slate-500">API</dt>
        <dd>{apiStatus}</dd>
        <dt className="text-slate-500">Database</dt>
        <dd>{databaseStatus}</dd>
      </dl>
    </section>
  )
}
