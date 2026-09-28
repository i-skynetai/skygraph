export function useApiQuery<T>(key: string): T {
  return load<T>(key);
}

function load<T>(key: string): T {
  return JSON.parse(key) as T;
}
