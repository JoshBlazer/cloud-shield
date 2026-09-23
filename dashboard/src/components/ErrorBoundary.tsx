import { Component } from 'react'
import { ErrorState } from './States'

/** Keeps one broken view from blanking the whole app. */
export class ErrorBoundary extends Component<{ children: React.ReactNode; resetKey?: string }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    // Navigating to another page clears the error.
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null })
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('View crashed', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="h-full overflow-y-auto">
          <ErrorState
            title="This page hit an unexpected error"
            detail={this.state.error.message}
            onRetry={() => this.setState({ error: null })}
          />
        </div>
      )
    }
    return this.props.children
  }
}
