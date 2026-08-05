import { useState, useEffect } from 'react';

const CONFIG_API = `http://${window.location.hostname}:8000/api/v1/config/llm`;

export default function Sidebar({ collapsed, onToggle }) {
  const [vendors, setVendors] = useState({});
  const [vendor, setVendor] = useState('deepseek');
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState('');
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  useEffect(() => {
    fetch(CONFIG_API)
      .then(r => r.json())
      .then(d => {
        setVendors(d.vendors || {});
        if (d.current) {
          setVendor(d.current.vendor || 'deepseek');
          setModel(d.current.model || '');
          setApiKey(d.current.api_key || '');
        }
      })
      .catch(() => {});
  }, []);

  const vendorList = Object.entries(vendors);

  const handleVendorChange = (v) => {
    setVendor(v);
    if (vendors[v]) setModel(vendors[v].default_model || '');
  };

  const save = async () => {
    setSaving(true);
    setMsg(null);
    try {
      const res = await fetch(CONFIG_API, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vendor, api_key: apiKey.trim(), model: model.trim() }),
      });
      const d = await res.json();
      setMsg({ ok: d.code === 200, text: d.message || (d.code === 200 ? '保存成功' : '保存失败') });
    } catch {
      setMsg({ ok: false, text: '网络错误' });
    } finally {
      setSaving(false);
    }
  };

  const s = collapsed ? { ...styles.sidebar, width: 0, padding: 0, overflow: 'hidden', borderRight: 'none' } : styles.sidebar;

  return (
    <>
      {/* 侧边栏 */}
      <div style={s}>
        <div style={styles.title}>⚙️ 模型配置</div>

        <div style={styles.group}>
          <label style={styles.label}>厂商</label>
          <select value={vendor} onChange={e => handleVendorChange(e.target.value)} style={styles.select}>
            {vendorList.map(([k, v]) => (
              <option key={k} value={k}>{v.label}</option>
            ))}
          </select>
        </div>

        <div style={styles.group}>
          <label style={styles.label}>API Key</label>
          <input
            type="password"
            value={apiKey}
            onChange={e => setApiKey(e.target.value)}
            placeholder="sk-..."
            style={styles.input}
          />
        </div>

        <div style={styles.group}>
          <label style={styles.label}>模型名称</label>
          <input
            value={model}
            onChange={e => setModel(e.target.value)}
            placeholder={vendors[vendor]?.default_model || ''}
            style={styles.input}
          />
        </div>

        <button onClick={save} disabled={saving} style={{ ...styles.btn, opacity: saving ? 0.6 : 1 }}>
          {saving ? '保存中...' : '💾 保存配置'}
        </button>

        {msg && (
          <div style={{ ...styles.msg, color: msg.ok ? '#1b5e20' : '#b71c1c', background: msg.ok ? '#e8f5e9' : '#ffebee' }}>
            {msg.text}
          </div>
        )}

        <div style={styles.hint}>
          切换厂商后自动清空推荐缓存，避免新旧模型评分混淆。
        </div>
      </div>

      {/* 收起/展开按钮 */}
      <div style={styles.toggleBtn} onClick={onToggle} title={collapsed ? '展开配置' : '收起配置'}>
        {collapsed ? '◀' : '▶'}
      </div>
    </>
  );
}

const styles = {
  sidebar: {
    position: 'fixed',
    top: 0,
    left: 0,
    width: 240,
    height: '100vh',
    background: '#fff',
    borderRight: '1px solid #e8eaed',
    padding: '20px 16px',
    boxSizing: 'border-box',
    zIndex: 100,
    overflowY: 'auto',
    transition: 'width 0.25s, padding 0.25s',
    boxShadow: '1px 0 4px rgba(0,0,0,0.04)',
  },
  title: {
    fontSize: 14,
    fontWeight: 600,
    marginBottom: 18,
    color: '#202124',
    whiteSpace: 'nowrap',
  },
  group: {
    marginBottom: 14,
    whiteSpace: 'nowrap',
  },
  label: {
    display: 'block',
    fontSize: 11,
    color: '#5f6368',
    marginBottom: 4,
  },
  select: {
    width: '100%',
    padding: '7px 10px',
    border: '1px solid #dadce0',
    borderRadius: 6,
    fontSize: 13,
    outline: 'none',
    background: '#fff',
    boxSizing: 'border-box',
  },
  input: {
    width: '100%',
    padding: '7px 10px',
    border: '1px solid #dadce0',
    borderRadius: 6,
    fontSize: 13,
    outline: 'none',
    boxSizing: 'border-box',
  },
  btn: {
    width: '100%',
    padding: '8px 0',
    border: 'none',
    borderRadius: 6,
    background: '#1a73e8',
    color: '#fff',
    fontSize: 13,
    cursor: 'pointer',
    marginTop: 4,
    whiteSpace: 'nowrap',
  },
  msg: {
    marginTop: 10,
    padding: '6px 10px',
    borderRadius: 4,
    fontSize: 12,
    whiteSpace: 'nowrap',
  },
  hint: {
    marginTop: 14,
    fontSize: 10,
    color: '#bbb',
    lineHeight: 1.5,
    whiteSpace: 'normal',
  },
  toggleBtn: {
    position: 'fixed',
    left: 0,
    top: '50%',
    transform: 'translateY(-50%)',
    zIndex: 101,
    width: 18,
    height: 48,
    background: '#f1f3f4',
    border: '1px solid #dadce0',
    borderLeft: 'none',
    borderRadius: '0 6px 6px 0',
    cursor: 'pointer',
    fontSize: 10,
    color: '#5f6368',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 0,
    transition: 'left 0.25s',
  },
};
