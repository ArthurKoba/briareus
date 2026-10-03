const ROW_ACTION_SELECTOR = [
  "button", "a", "input", "select", "textarea", "label", "summary",
  '[role="button"]', '[role="link"]', '[role="switch"]', '[role="checkbox"]',
  '[role="combobox"]', '[contenteditable]:not([contenteditable="false"])',
  "[data-row-action]",
].join(",")

/** A row activates only for an unhandled click on its non-interactive content. */
export function isRowContentClick(event: MouseEvent): boolean {
  if (event.defaultPrevented || event.button !== 0) return false
  const row = event.currentTarget
  if (!(row instanceof Element)) return false
  // A target removed/moved by its own handler must not cause a second row action.
  if (event.target instanceof Node && !row.contains(event.target)) return false

  // The dispatch path survives DOM replacements (e.g. an SVG becomes a spinner).
  // Walking current target.closest() alone loses the button boundary in that case.
  const path = event.composedPath()
  for (const target of path) {
    if (target === row) break
    if (target instanceof Element && target.matches(ROW_ACTION_SELECTOR)) return false
  }
  // Also support synthetic callers without a dispatch path, bounded to this row.
  if (!path.length && event.target instanceof Element) {
    const action = event.target.closest(ROW_ACTION_SELECTOR)
    if (action && action !== row && row.contains(action)) return false
  }

  const selection = row.ownerDocument.getSelection()
  if (selection && !selection.isCollapsed) {
    for (let index = 0; index < selection.rangeCount; index++) {
      if (selection.getRangeAt(index).intersectsNode(row)) return false
    }
  }
  return true
}
