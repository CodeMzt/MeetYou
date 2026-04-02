import { useState, useEffect, useCallback } from 'react';

export interface ConfigEntry {
  key: string;
  value: any;
  is_secret: boolean;
  has_value: boolean;
  source: string;
  env_key: string | null;
}

export function useConfig(baseUrl: string = 'http://127.0.0.1:8000') {
  const [config, setConfig] = useState<Record<string, ConfigEntry>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchConfig = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch(`${baseUrl}/config`);
      if (!res.ok) throw new Error('Failed to fetch config');
      const data = await res.json();
      setConfig(data.items);
      setError(null);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [baseUrl]);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const updateConfig = async (updates: Record<string, any>) => {
    try {
      const res = await fetch(`${baseUrl}/config`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ updates })
      });
      if (!res.ok) throw new Error('Failed to update config');
      await fetchConfig(); // Refresh after update
      return true;
    } catch (err: any) {
      setError(err.message);
      return false;
    }
  };

  return { config, loading, error, refresh: fetchConfig, updateConfig };
}
