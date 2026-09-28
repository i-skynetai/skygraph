import { useApiQuery } from '../hooks/useApiQuery';

export class ListPage {
  load() {
    return useApiQuery<string[]>('list');
  }

  refresh() {
    return this.load();
  }
}
