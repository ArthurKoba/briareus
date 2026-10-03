export type ManagementApiErrorKind = "http" | "network" | "aborted"

export class ManagementApiError extends Error {
  constructor(
    message: string,
    readonly kind: ManagementApiErrorKind,
    readonly status: number | null = null,
    readonly code: string = "",
    readonly requestId: string = "",
    options: ErrorOptions = {},
  ) {
    super(message, options)
    this.name = "ManagementApiError"
  }
}
