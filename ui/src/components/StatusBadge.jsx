const statusStyles = {
  success: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  error: 'bg-red-500/15 text-red-400 border-red-500/30',
  timeout: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  running: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  idle: 'bg-gray-500/15 text-gray-400 border-gray-500/30',
  dryrun: 'bg-violet-500/15 text-violet-400 border-violet-500/30',
}

export default function StatusBadge({ status }) {
  const style = statusStyles[status] || statusStyles.idle
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${style}`}>
      {status === 'running' && (
        <span className="w-1.5 h-1.5 bg-blue-400 rounded-full mr-1.5 animate-pulse" />
      )}
      {status}
    </span>
  )
}
