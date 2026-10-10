import type { queries, BoundFunctions } from "@testing-library/dom";

declare module "@testing-library/dom" {
  export function within(element: Element): BoundFunctions<typeof queries>;
}
