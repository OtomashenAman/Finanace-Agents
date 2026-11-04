import type { LineIn, PurchaseRequest, RequestIn } from "./api"

export const EMPTY_LINE: LineIn = {
  description: "",
  quantity: "1",
  unit: null,
  unit_price: null,
  category: null,
  catalogue_item_code: null,
}

export function emptyRequest(): RequestIn {
  return {
    title: "",
    purpose: "",
    needed_by: null,
    cost_centre_code: null,
    lab_code: null,
    project_code: null,
    grant_code: null,
    lines: [{ ...EMPTY_LINE }],
    source_text: null,
  }
}

/** The form's values for an existing request. */
export function fromRequest(r: PurchaseRequest): RequestIn {
  return {
    title: r.title,
    purpose: r.purpose,
    needed_by: r.needed_by,
    cost_centre_code: r.cost_centre_code,
    lab_code: r.lab_code,
    project_code: r.project_code,
    grant_code: r.grant_code,
    lines: r.lines.map((l) => ({
      description: l.description,
      quantity: l.quantity,
      unit: l.unit,
      unit_price: l.unit_price,
      category: l.category,
      catalogue_item_code: l.catalogue_item_code,
    })),
    source_text: r.source_text,
  }
}
