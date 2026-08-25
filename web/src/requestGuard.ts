export type LatestRequestGuard = {
  begin: () => number;
  isCurrent: (token: number) => boolean;
  invalidate: () => void;
};

export function createLatestRequestGuard(): LatestRequestGuard {
  let generation = 0;
  return {
    begin: () => ++generation,
    isCurrent: (token) => token === generation,
    invalidate: () => { generation += 1; },
  };
}
