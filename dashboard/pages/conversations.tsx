import { useEffect, useState } from 'react';

export default function Conversations() {
  const [rows, setRows] = useState<any[]>([]);
  const [vol, setVol] = useState<any>(null);
  const base = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8080';
  useEffect(()=>{
    (async()=>{
      const a = await fetch(base + '/admin/conversations?hours=24');
      const b = await fetch(base + '/admin/volume?hours=24&compare=24');
      setRows((await a.json()).conversations || []);
      setVol(await b.json());
    })();
  },[]);
  return (
    <main style={{padding:20}}>
      <h1>Conversations (last 24h)</h1>
      {vol && <div style={{fontFamily:'monospace'}}>current={vol.current} prev={vol.previous} delta={vol.delta} delta_pct={vol.delta_pct}</div>}
      <table style={{width:'100%', borderCollapse:'collapse', marginTop:8}}>
        <thead>
          <tr>
            <th align="left">id</th>
            <th align="left">number</th>
            <th align="left">subject</th>
            <th align="left">updated</th>
            <th align="left">tags</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r)=> (
            <tr key={r.id}>
              <td>{r.id}</td>
              <td>{r.number}</td>
              <td>{r.subject}</td>
              <td>{r.updated_at}</td>
              <td>{(r.tags||[]).join(', ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
