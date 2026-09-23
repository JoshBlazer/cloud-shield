/** An API failure with enough detail for the UI to say something useful. */
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}
