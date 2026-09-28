// Items the user leaves partly empty (a goal's horizon, a task's urgency/effort) get an AI guess
// in the background. For a short while after creation the UI says "MyPA is suggesting…" and
// re-checks the item (goals plan §1.4, tasks plan §1.5).
export const GUESS_WINDOW_MS = 20_000;
export const GUESS_POLL_MS = 3000;

/** Whether an item created at `createdAt` is still inside its AI-guess window. */
export function isInGuessWindow(createdAt: string, now: number = Date.now()): boolean {
  return now - new Date(createdAt).getTime() < GUESS_WINDOW_MS;
}
