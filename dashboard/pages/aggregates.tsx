import { useEffect, useState } from 'react';

export default function Aggregates() {
  const [items, setItems] = useState<any[]>([]);
  const [topics, setTopics] = useState<any>(null);
  const base = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8080';
  useEffect(()=>{
    (async()=>{
      const agg = await fetch(base + '/admin/aggregates?hours=24&limit=50');
      const ts = await fetch(base + '/admin/topic-stats?hours=24');
      setItems((await agg.json()).aggregates || []);
      setTopics(await ts.json());
    })();
  },[]);
  return (
    <main style={{padding:20}}>
      <h1>Aggregates (last 24h)</h1>
      {topics && (
        <div style={{fontFamily:'monospace'}}>
          total={topics.total} crash_count={topics.crash_count} by_category={JSON.stringify(topics.by_category)}
        </div>
      )}
      {items.map((g)=> (
        <div key={g.cluster_key} style={{border:'1px solid #ddd', padding:12, margin:'12px 0'}}>
          <div style={{fontWeight:600}}>count={g.count} categories={(g.categories||[]).join(', ')}</div>
          <div style={{color:'#666'}}>{(g.top_subjects||[]).join(' | ')}</div>
          {g.sample_text && <pre style={{whiteSpace:'pre-wrap', background:'#f7f7f7', padding:8}}>{g.sample_text}</pre>}
        </div>
      ))}
    </main>
  );
}
