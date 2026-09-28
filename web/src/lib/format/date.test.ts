import { describe, expect, it } from "vitest";

import { dayOf, formatDay, isOverdue, todayIn } from "./date";

// 25 Sep 2026, 23:30 UTC: already the 26th in Lagos (UTC+1), still the 25th in New York (UTC-4).
const NOW = new Date("2026-09-25T23:30:00Z");

describe("formatDay", () => {
  it("says Today and Tomorrow in the user's timezone", () => {
    expect(formatDay("2026-09-25", "America/New_York", NOW)).toBe("Today");
    expect(formatDay("2026-09-26", "America/New_York", NOW)).toBe("Tomorrow");
    expect(formatDay("2026-09-26", "Africa/Lagos", NOW)).toBe("Today");
  });

  it("uses weekday, day and month within the same year", () => {
    expect(formatDay("2026-10-02", "UTC", NOW)).toBe("Fri 2 Oct");
  });

  it("always uses three-letter months (not en-GB's 'Sept')", () => {
    expect(formatDay("2026-09-29", "UTC", NOW)).toBe("Tue 29 Sep");
  });

  it("adds the year for other years", () => {
    expect(formatDay("2027-10-03", "UTC", NOW)).toBe("3 Oct 2027");
  });
});

describe("todayIn / dayOf / isOverdue", () => {
  it("works out the calendar day in a timezone", () => {
    expect(todayIn("Africa/Lagos", NOW)).toBe("2026-09-26");
    expect(dayOf("2026-09-25T23:30:00Z", "America/New_York")).toBe("2026-09-25");
  });

  it("treats only earlier days as overdue", () => {
    expect(isOverdue("2026-09-24", "UTC", NOW)).toBe(true);
    expect(isOverdue("2026-09-25", "UTC", NOW)).toBe(false);
  });
});
