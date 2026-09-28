// Calendar dates from the API (`target_date`, `due_date`) are plain `YYYY-MM-DD` strings with no
// time or zone, so they're formatted as-is (in UTC, which never shifts them). "Today" is decided in
// the user's own timezone (from their profile), not the browser's.

/** Today's date in `timeZone`, as `YYYY-MM-DD`. */
export function todayIn(timeZone: string, now: Date = new Date()): string {
  // en-CA formats as YYYY-MM-DD.
  return new Intl.DateTimeFormat("en-CA", { timeZone }).format(now);
}

/** The calendar day an instant (`created_at`) falls on in `timeZone`, as `YYYY-MM-DD`. */
export function dayOf(isoDateTime: string, timeZone: string): string {
  return todayIn(timeZone, new Date(isoDateTime));
}

export function addDays(isoDate: string, days: number): string {
  const date = new Date(`${isoDate}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function parts(isoDate: string, options: Intl.DateTimeFormatOptions): Record<string, string> {
  // Parts only (the order is assembled below). en-US for three-letter months: en-GB now says "Sept".
  const formatted = new Intl.DateTimeFormat("en-US", { ...options, timeZone: "UTC" }).formatToParts(
    new Date(`${isoDate}T00:00:00Z`),
  );
  return Object.fromEntries(formatted.map((part) => [part.type, part.value]));
}

/** "Today" / "Tomorrow" / "Fri 3 Oct" (this year) / "3 Oct 2027" (other years). design-system §7.3. */
export function formatDay(isoDate: string, timeZone: string, now: Date = new Date()): string {
  const today = todayIn(timeZone, now);
  if (isoDate === today) return "Today";
  if (isoDate === addDays(today, 1)) return "Tomorrow";

  if (isoDate.slice(0, 4) === today.slice(0, 4)) {
    const { weekday, day, month } = parts(isoDate, { weekday: "short", day: "numeric", month: "short" });
    return `${weekday} ${day} ${month}`;
  }
  const { day, month, year } = parts(isoDate, { day: "numeric", month: "short", year: "numeric" });
  return `${day} ${month} ${year}`;
}

/** Before today in `timeZone`. */
export function isOverdue(isoDate: string, timeZone: string, now: Date = new Date()): boolean {
  return isoDate < todayIn(timeZone, now);
}

/** "Added today" / "Added Fri 3 Oct" for an item's `created_at`. */
export function formatAdded(createdAt: string, timeZone: string, now: Date = new Date()): string {
  const day = formatDay(dayOf(createdAt, timeZone), timeZone, now);
  return `Added ${day === "Today" ? "today" : day}`;
}
