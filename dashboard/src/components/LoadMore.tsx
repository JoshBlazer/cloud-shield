interface Props {
  loaded:      number
  hasMore:     boolean
  loadingMore: boolean
  error:       string | null
  onLoadMore:  () => void
}

/** Footer for cursor-paginated lists: loaded count plus a "Load more" button. */
export function LoadMore({ loaded, hasMore, loadingMore, error, onLoadMore }: Props) {
  return (
    <div className="flex flex-col items-center gap-2 pt-2 pb-4">
      {error && (
        <p className="text-[11px]" style={{ color: '#f87171' }}>Couldn't load more: {error}</p>
      )}
      {hasMore ? (
        <button
          className="btn btn-secondary"
          onClick={onLoadMore}
          disabled={loadingMore}
          style={loadingMore ? { opacity: 0.6, cursor: 'default' } : undefined}
        >
          {loadingMore ? 'Loading…' : error ? 'Retry' : 'Load more'}
        </button>
      ) : null}
      <p className="text-[11px] tabular-nums" style={{ color: '#4b5568' }}>
        {hasMore
          ? `Showing ${loaded} loaded · more available`
          : `Showing all ${loaded} violation${loaded !== 1 ? 's' : ''}`}
      </p>
    </div>
  )
}
