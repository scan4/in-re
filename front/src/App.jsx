import { useState, useEffect, useRef, useMemo } from 'react';
import Sidebar from './Sidebar';

// 后端独立开放 8000 端口，前端直连（window.location.hostname 自动取服务器 IP）
const API_HOST = window.location.hostname;
const API_STREAM = `http://${API_HOST}:8000/api/v1/recommend/stream`;

const SECTIONS = [
  { key: 'course', label: '感兴趣的课程', icon: '📚', color: '#1b5e20', bg: '#e8f5e9' },
  { key: 'training', label: '相关培训班', icon: '📋', color: '#e65100', bg: '#fff3e0' },
  { key: 'skill', label: '相关技能岗位', icon: '💼', color: '#0d47a1', bg: '#e3f2fd' },
  { key: 'scale', label: '相关测评量表', icon: '📊', color: '#6a1b9a', bg: '#f3e5f5' },
  { key: 'career', label: '职业规划方案', icon: '🎯', color: '#4a148c', bg: '#ede7f6' },
  { key: 'news', label: '相关资讯', icon: '📰', color: '#e65100', bg: '#fff8e1' },
];

// 从 URL ?token=... 拿 JWT，再手动解码 payload 取用户名 (展示用，不需要验签)
function parseToken(urlParams) {
  const token = urlParams.get('token') || urlParams.get('tokens') || urlParams.get('t') || '';
  let userName = '';
  if (token) {
    try {
      const parts = token.split('.');
      if (parts.length === 3) {
        const payload = JSON.parse(atob(parts[1]));
        userName = payload.username || payload.uname || '';
      }
    } catch {}
  }
  return { token, userName };
}

export default function App() {
  const { token, userName } = useMemo(() => parseToken(new URLSearchParams(window.location.search)), []);
  const [results, setResults] = useState({});
  const [loading, setLoading] = useState(false);
  const [loadedTypes, setLoadedTypes] = useState(new Set());
  const [error, setError] = useState(null);
  const [sbCollapsed, setSbCollapsed] = useState(false);
  const esRef = useRef(null);
  const hasToken = !!token;

  const streamAll = (contextText) => {
    if (!hasToken) return;
    setLoading(true);
    setError(null);
    setResults({});
    setLoadedTypes(new Set());

    // 关闭旧的连接
    if (esRef.current) esRef.current.close();

    // 用 fetch + ReadableStream (EventSource 不支持 POST)
    const abort = new AbortController();
    fetch(API_STREAM, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, context_type: 'browsing', context_text: contextText, limit: 4 }),
      signal: abort.signal,
    }).then(async (res) => {
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // 按 \n\n 分割 SSE 事件
        const parts = buffer.split('\n\n');
        buffer = parts.pop(); // 保留未完成的部分

        for (const part of parts) {
          const dataLine = part.split('\n').find(l => l.startsWith('data: '));
          if (!dataLine) continue;
          const jsonStr = dataLine.slice(6);
          if (jsonStr === '[DONE]') {
            setLoading(false);
            return;
          }
          try {
            const chunk = JSON.parse(jsonStr);
            setResults(prev => ({
              ...prev,
              [chunk.type]: chunk.items || [],
            }));
            setLoadedTypes(prev => new Set([...prev, chunk.type]));
          } catch {}
        }
      }
    }).catch(() => {
      setLoading(false);
      setError('连接中断');
    });

    esRef.current = { close: () => abort.abort() };
  };

  useEffect(() => {
    if (hasToken) streamAll('推荐内容');
    return () => { if (esRef.current) esRef.current.close(); };
  }, []);

  const contentLeft = sbCollapsed ? 20 : 260;

  if (!hasToken) {
    return (<>
      <Sidebar collapsed={sbCollapsed} onToggle={() => setSbCollapsed(v => !v)} />
      <div style={{ fontFamily: '-apple-system, BlinkMacSystemFont, sans-serif', color: '#202124', maxWidth: 820, marginLeft: contentLeft, marginRight: 'auto', padding: 20, transition: 'margin-left 0.25s' }}>
        <div style={{ textAlign: 'center', padding: '60px 20px', color: '#999' }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>🔒</div>
          <div style={{ fontSize: 16, fontWeight: 500, color: '#5f6368', marginBottom: 6 }}>未检测到登录信息</div>
          <div style={{ fontSize: 13 }}>请从平台入口访问，或传入 <code style={{ background: '#f0f0f0', padding: '2px 6px', borderRadius: 3 }}>?token=</code> 参数</div>
        </div>
      </div>
    </>);
  }

  return (<>
    <Sidebar collapsed={sbCollapsed} onToggle={() => setSbCollapsed(v => !v)} />

    <div style={{ fontFamily: '-apple-system, BlinkMacSystemFont, sans-serif', color: '#202124', maxWidth: 820, marginLeft: contentLeft, marginRight: 'auto', padding: 20, transition: 'margin-left 0.25s' }}>

      <h3 style={{ fontSize: 18, fontWeight: 600, marginBottom: 6 }}>📌 为您推荐</h3>
      <p style={{ fontSize: 12, color: '#999', marginBottom: 20 }}>
        当前用户：<strong>{userName || '未知'}</strong>
        {loading && ' · 加载中...'}
      </p>

      {error && <p style={{ textAlign:'center', padding:40, color:'#999' }}>加载失败</p>}

      {SECTIONS.map(section => {
        const items = results[section.key] || [];
        const isLoaded = loadedTypes.has(section.key);
        return (
          <div key={section.key} style={{ marginBottom: 24 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, paddingBottom: 6, borderBottom: `2px solid ${section.bg}` }}>
              <span style={{ fontSize: 16 }}>{section.icon}</span>
              <h4 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>{section.label}</h4>
              {isLoaded ? (
                <span style={{ fontSize: 11, color: '#999' }}>({items.length})</span>
              ) : (
                <span style={{ fontSize: 11, color: '#f9ab00' }}>加载中...</span>
              )}
            </div>
            {!isLoaded ? (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 10 }}>
                {[1,2,3].map(i => <div key={i} style={{ height: 64, borderRadius: 8, background: 'linear-gradient(90deg, #f5f5f5 25%, #e8e8e8 50%, #f5f5f5 75%)', backgroundSize: '200% 100%', animation: 'shimmer 1.5s infinite' }} />)}
              </div>
            ) : items.length > 0 ? (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 10 }}>
                {items.map((r, i) => (
                  <div key={i} style={{ background: '#fff', borderRadius: 8, padding: '10px 14px', boxShadow: '0 1px 3px rgba(0,0,0,0.06)', border: `1px solid ${section.bg}`, borderLeft: `3px solid ${section.color}` }}>
                    <div style={{ fontWeight: 500, fontSize: 13, marginBottom: 4 }}>{r.title}</div>
                    <div style={{ fontSize: 11, color: '#5f6368', lineHeight: 1.4, marginBottom: 4 }}>{r.reason}</div>
                    <span style={{ fontSize: 11, color: '#f9ab00' }}>{'★'.repeat(Math.round((r.score||0.5)*5))} {Math.round((r.score||0.5)*100)}%</span>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ padding: '14px 16px', borderRadius: 6, background: '#fafafa', border: '1px dashed #e0e0e0', textAlign: 'center', fontSize: 12, color: '#bbb' }}>暂无推荐</div>
            )}
          </div>
        );
      })}
    </div>
  </>);
}
