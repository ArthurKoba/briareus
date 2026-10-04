export type AdminApiErrorKind = "http" | "network" | "aborted"

export class AdminApiError extends Error {
  constructor(
    message: string,
    readonly kind: AdminApiErrorKind,
    readonly status: number | null = null,
    readonly code: string = "",
    readonly requestId: string = "",
    options: ErrorOptions = {},
  ) {
    super(message, options)
    this.name = "AdminApiError"
  }
}
