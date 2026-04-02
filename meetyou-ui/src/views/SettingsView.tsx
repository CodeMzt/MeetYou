import { useState, useEffect } from 'react';
import { useConfig } from '../hooks/useConfig';

export default function SettingsView() {
  const { config, loading, error, updateConfig } = useConfig();
  const [localConfig, setLocalConfig] = useState<Record<string, any>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!loading && config) {
      const mapped: Record<string, any> = {};
      Object.keys(config).forEach(k => {
        mapped[k] = config[k].value;
      });
      setLocalConfig(mapped);
    }
  }, [config, loading]);

  const handleChange = (key: string, value: any) => {
    setLocalConfig(prev => ({ ...prev, [key]: value }));
  };

  const handleSave = async () => {
    setSaving(true);
    const updates: Record<string, any> = {};
    Object.keys(localConfig).forEach(k => {
      if (localConfig[k] !== config[k]?.value) {
        updates[k] = localConfig[k];
      }
    });

    if (Object.keys(updates).length > 0) {
      await updateConfig(updates);
    }
    setSaving(false);
  };

  if (loading) return <div>正在加载设置...</div>;
  if (error) return <div style={{ color: '#ff3b30' }}>错误: {error}</div>;

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      <div style={{ padding: '20px 24px', borderBottom: '1px solid var(--glass-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ fontSize: 18, fontWeight: 600 }}>系统配置</h2>
        <button 
          onClick={handleSave} 
          disabled={saving}
          style={{ 
            background: 'var(--accent-color)', color: 'white', border: 'none', 
            padding: '8px 16px', borderRadius: 8, cursor: saving ? 'not-allowed' : 'pointer',
            opacity: saving ? 0.7 : 1, fontWeight: 500 
          }}
        >
          {saving ? '保存中...' : '保存更改'}
        </button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: 24, display: 'flex', flexDirection: 'column', gap: 24 }}>
        <section>
          <h3 style={{ fontSize: 14, color: 'var(--text-secondary)', marginBottom: 16, textTransform: 'uppercase' }}>深度思考 (Reasoning)</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr', gap: '16px 24px', alignItems: 'center' }}>
            <label style={{ fontSize: 13, fontWeight: 500 }}>启用思考</label>
            <div>
              <input 
                type="checkbox" 
                checked={!!localConfig['thinking_enabled']} 
                onChange={e => handleChange('thinking_enabled', e.target.checked)} 
              />
            </div>

            <label style={{ fontSize: 13, fontWeight: 500 }}>思考强度</label>
            <select 
              value={localConfig['thinking_effort'] || 'low'}
              onChange={e => handleChange('thinking_effort', e.target.value)}
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--glass-border)', background: 'transparent', color: 'var(--text-primary)' }}
            >
              <option value="low">低 (Low)</option>
              <option value="medium">中等 (Medium)</option>
              <option value="high">高 (High)</option>
            </select>

            <label style={{ fontSize: 13, fontWeight: 500 }}>思考 Token 预算</label>
            <input 
              type="number" 
              value={localConfig['thinking_budget_tokens'] || 0}
              onChange={e => handleChange('thinking_budget_tokens', parseInt(e.target.value) || 0)}
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--glass-border)', background: 'transparent', color: 'var(--text-primary)' }}
            />
          </div>
        </section>

        <div style={{ height: 1, background: 'var(--glass-border)' }} />

        <section>
          <h3 style={{ fontSize: 14, color: 'var(--text-secondary)', marginBottom: 16, textTransform: 'uppercase' }}>API 供应商设置</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr', gap: '16px 24px', alignItems: 'center' }}>
            <label style={{ fontSize: 13, fontWeight: 500 }}>API 供应商</label>
            <input 
              type="text" 
              value={localConfig['api_provider'] || ''}
              onChange={e => handleChange('api_provider', e.target.value)}
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--glass-border)', background: 'transparent', color: 'var(--text-primary)', width: '100%', maxWidth: 300 }}
            />

            <label style={{ fontSize: 13, fontWeight: 500 }}>模型</label>
            <input 
              type="text" 
              value={localConfig['model'] || ''}
              onChange={e => handleChange('model', e.target.value)}
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--glass-border)', background: 'transparent', color: 'var(--text-primary)', width: '100%', maxWidth: 300 }}
            />
            
            <label style={{ fontSize: 13, fontWeight: 500 }}>API URL</label>
            <input 
              type="text" 
              value={localConfig['api_url'] || ''}
              onChange={e => handleChange('api_url', e.target.value)}
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid var(--glass-border)', background: 'transparent', color: 'var(--text-primary)', width: '100%', maxWidth: 300 }}
            />
          </div>
        </section>
      </div>
    </div>
  );
}
