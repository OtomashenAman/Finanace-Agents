/**
 * Per-tab sessions: each tab sends its own slot id (X-Session-Slot) and the API keeps that
 * tab's login in cookies named after the slot (still httpOnly). An admin and a user can then
 * be signed in side by side in one browser.
 *
 * sessionStorage is per tab, so the slot survives reloads and the QuickBooks round trip. A new
 * tab starts on the most recently signed-in slot (localStorage), i.e. the same account.
 */

const TAB_KEY = "facc-session-slot"
const LAST_KEY = "facc-last-session-slot"
const VALID = /^[a-z0-9]{8,32}$/

function read(storage: () => Storage, key: string): string | null {
  try {
    const value = storage().getItem(key)
    return value && VALID.test(value) ? value : null
  } catch {
    return null // storage blocked (private mode, policies): fall back to a fresh slot
  }
}

function write(storage: () => Storage, key: string, value: string) {
  try {
    storage().setItem(key, value)
  } catch {
    // the slot then lasts until the tab reloads
  }
}

function newSlotId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(8))
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")
}

let current: string | null = null

export function sessionSlot(): string {
  if (current === null) {
    current =
      read(() => sessionStorage, TAB_KEY) ?? read(() => localStorage, LAST_KEY) ?? newSlotId()
    write(() => sessionStorage, TAB_KEY, current)
  }
  return current
}

/** After signing in: new tabs open with this account */
export function rememberSlot() {
  write(() => localStorage, LAST_KEY, sessionSlot())
}

/** Sign in with another account in this tab, leaving the other tabs' sessions untouched */
export function startNewSlot() {
  current = newSlotId()
  write(() => sessionStorage, TAB_KEY, current)
}

export const SLOT_HEADER = "X-Session-Slot"
