export function Loading({ what }: { what: string }) {
  return <div className="status status-loading">Loading {what}…</div>
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="status status-error">
      <span>{message}</span>
      {onRetry && <button onClick={onRetry}>Retry</button>}
    </div>
  )
}
