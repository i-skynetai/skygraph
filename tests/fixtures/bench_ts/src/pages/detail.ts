import { useApiQuery } from '../hooks/useApiQuery';

export function detail(id: string) {
  return useApiQuery('detail/' + id);
}
