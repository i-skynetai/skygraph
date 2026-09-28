import { useApiQuery } from '@hooks/useApiQuery';

export function viaAlias() {
  return useApiQuery<number>('count');
}
