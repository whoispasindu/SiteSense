import "@testing-library/jest-dom/vitest";

import { cleanup, configure, getRoles, queryAllByRole } from "@testing-library/react";
import { afterEach, beforeAll, expect } from "vitest";

import { axeViolations } from "./axe";

// jsdom has no layout engine: give Recharts' ResponsiveContainer an observer to attach to.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
if (!("ResizeObserver" in globalThis)) {
  Object.defineProperty(globalThis, "ResizeObserver", { value: ResizeObserverStub, writable: true });
}

// Warm up the accessibility engine once per test file, before any test starts its clock.
//
// Every test file gets a fresh jsdom. The first role query in it compiles jsdom's selector engine for
// the ARIA role selectors and computes styles cold, which costs around 0.6 s under coverage. A
// `findByRole` that is waiting for a page re-runs its query on every DOM change while the app boots,
// so those cold queries starved the app and the first test in a file could miss the 1 s default
// (issue #17). Paying the cost here keeps the default timeout meaningful for the app itself.
const WARM_UP_MARKUP = `
  <header><nav aria-label="Menu"><a href="/">Home</a><button type="button">Open</button></nav></header>
  <main>
    <h1>Title</h1>
    <section aria-label="Section">
      <ul><li>Item</li></ul>
      <table><caption>Table</caption><thead><tr><th scope="col">Head</th></tr></thead><tbody><tr><th scope="row">Row</th><td>Cell</td></tr></tbody></table>
      <form aria-label="Form">
        <label>Text <input /></label><label>Choice <select><option>One</option></select></label>
        <label>Notes <textarea></textarea></label><input type="checkbox" aria-label="Check" /><input type="radio" aria-label="Pick" />
      </form>
      <dl><dt>Term</dt><dd>Detail</dd></dl><img alt="Image" /><p style="width: 50%">Text</p>
      <div role="dialog" aria-label="Dialog" hidden><button type="button">Close</button></div>
    </section>
  </main>`;

// What is left after the warm-up is CPU contention while the suite starts: Vitest runs the longest
// files first, and their first test renders while every other worker is still loading. Measured on a
// 12-thread laptop with coverage, those first page loads take up to about 2.6 s; everything else stays
// well under 1 s. 3 s is a ceiling for that start-up window, not a wait for anything in particular:
// tests wait on the real element with findBy*/waitFor.
configure({ asyncUtilTimeout: 3000 });

beforeAll(() => {
  const container = document.createElement("div");
  container.append(...new DOMParser().parseFromString(WARM_UP_MARKUP, "text/html").body.childNodes);
  document.body.append(container);
  getRoles(container);
  queryAllByRole(container, "button", { name: "Open" });
  container.remove();
});

// Phase 13: every screen the tests leave behind must pass axe (WCAG 2.2 A and AA) before it is cleaned
// up, so a new page, dialog or state that breaks accessibility fails the test that renders it.
afterEach(async () => {
  const problems = document.body.textContent.trim() ? await axeViolations() : [];
  cleanup();
  expect(problems, "axe found accessibility problems on this screen").toEqual([]);
});
