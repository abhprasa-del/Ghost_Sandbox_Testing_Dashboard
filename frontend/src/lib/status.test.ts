import { describe, expect, it } from "vitest";
import { jobLabel, jobTone } from "./status";

describe("jobTone", () => {
  it("maps statuses to colours", () => {
    expect(jobTone("Completed", "PASSED")).toBe("green");
    expect(jobTone("Completed", "NA")).toBe("green");
    expect(jobTone("FAILURE")).toBe("red");
    expect(jobTone("TIMEOUT", "NO_INFO")).toBe("red");
    expect(jobTone("RUNNING")).toBe("amber");
    expect(jobTone("STARTING")).toBe("amber");
    expect(jobTone("UNSTABLE")).toBe("amber");
    expect(jobTone("SKIPPED")).toBe("grey");
    expect(jobTone(null)).toBe("grey");
  });
  it("treats a DEGRADED outcome as amber even when Completed", () => {
    expect(jobTone("Completed", "DEGRADED")).toBe("amber");
    expect(jobLabel("Completed", "DEGRADED")).toBe("Degraded");
  });
  it("is case-insensitive on status", () => {
    expect(jobTone("failure")).toBe("red");
  });
});

describe("jobLabel", () => {
  it("labels missing jobs", () => {
    expect(jobLabel(null, null, true)).toBe("Not selected");
    expect(jobLabel(null)).toBe("—");
    expect(jobLabel("UNSTABLE")).toBe("UNSTABLE");
  });
});
