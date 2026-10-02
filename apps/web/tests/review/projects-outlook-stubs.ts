/** Fail closed if a review accidentally mounts a source-connected container. */
export function useUser(): never {
  throw new Error("The synthetic review cannot read an account");
}
export function useCurveProjects(): never {
  throw new Error("The synthetic review cannot read source records");
}
