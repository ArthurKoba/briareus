export type TableState = "data" | "empty" | "error" | "loading" | "refreshing"

export interface DataTableColumn {
  title?: string
  dataIndex?: string
  key?: string
  width?: number
  sortable?: boolean
  align?: "left" | "center" | "right"
}
