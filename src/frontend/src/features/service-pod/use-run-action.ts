import type { CaseActionName, CaseDetail } from "./api"
import { useCaseAction } from "./hooks"
import { attempt } from "./ui"

/** Run a case action against the version on screen (409 if someone changed it since). */
export function useRunAction(c: CaseDetail) {
  const action = useCaseAction()
  return {
    pending: action.isPending,
    run: (name: CaseActionName, payload: Record<string, unknown>, success: string) =>
      attempt(() => action.mutateAsync({ id: c.id, action: name, version: c.version, payload }), success),
  }
}
